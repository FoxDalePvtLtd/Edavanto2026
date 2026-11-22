import logging
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.auth_services import create_otp, normalize_email
from core.models import (
    AuditLog,
    Center,
    CenterApplication,
    CenterInstructor,
    CenterSubscription,
    CenterSubscriptionPayment,
    CenterSubscriptionPlan,
    Course,
    CourseApprovalHistory,
    Notification,
    NotificationDelivery,
    OTPVerification,
    SecurityEvent,
    User,
)
from core.services.notification import create_admin_notification
from core.services.payments import get_razorpay_client

logger = logging.getLogger(__name__)


# ============================================================
# CENTER REGISTRATION & APPLICATION VALIDATION
# ============================================================

def validate_center_application_data(data, files=None):
    """
    Validate public center registration form data before sending OTP.
    """
    errors = {}

    center_name = (data.get("center_name") or "").strip()
    official_email = normalize_email(data.get("official_email") or "")
    contact_number = (data.get("contact_number") or "").strip()
    address = (data.get("address") or "").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "").strip()
    postal_code = (data.get("postal_code") or "").strip()
    website = (data.get("website") or "").strip()
    description = (data.get("description") or "").strip()

    owner_name = (data.get("owner_name") or "").strip()
    owner_email = normalize_email(data.get("owner_email") or "")
    owner_phone = (data.get("owner_phone") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    # Required field checks
    if not center_name:
        errors["center_name"] = "Center name is required."
    if not official_email:
        errors["official_email"] = "Center official email is required."
    if not contact_number:
        errors["contact_number"] = "Center contact number is required."
    if not address:
        errors["address"] = "Center address is required."
    if not city:
        errors["city"] = "City is required."
    if not state:
        errors["state"] = "State is required."
    if not postal_code:
        errors["postal_code"] = "Postal code is required."

    if not owner_name:
        errors["owner_name"] = "Owner full name is required."
    if not owner_email:
        errors["owner_email"] = "Owner email is required."
    if not owner_phone:
        errors["owner_phone"] = "Owner mobile number is required."

    if not password:
        errors["password"] = "Password is required."
    elif password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors["password"] = " ".join(exc.messages)

    # Prevent duplicate accounts & duplicate applications
    if owner_email:
        if User.objects.filter(username=owner_email).exists() or User.objects.filter(email=owner_email).exists():
            errors["owner_email"] = "An account with this email address already exists."
        elif CenterApplication.objects.filter(
            owner_email=owner_email,
            status__in=[
                CenterApplication.Status.PENDING,
                CenterApplication.Status.UNDER_REVIEW,
                CenterApplication.Status.APPROVED,
            ],
        ).exists():
            errors["owner_email"] = "An active or pending application already exists for this owner email."

    if official_email:
        if Center.objects.filter(email=official_email).exists():
            errors["official_email"] = "A registered center with this email already exists."
        elif CenterApplication.objects.filter(
            official_email=official_email,
            status__in=[
                CenterApplication.Status.PENDING,
                CenterApplication.Status.UNDER_REVIEW,
                CenterApplication.Status.APPROVED,
            ],
        ).exists():
            errors["official_email"] = "An active or pending application already exists for this center email."

    # Validate uploaded files if present
    if files:
        allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}
        max_size_bytes = 10 * 1024 * 1024  # 10MB
        for field in ["business_registration_doc", "identity_doc", "supporting_doc"]:
            file_obj = files.get(field)
            if file_obj:
                name = file_obj.name.lower()
                if not any(name.endswith(ext) for ext in allowed_extensions):
                    errors[field] = "Allowed file types: PDF, PNG, JPG, JPEG, DOC, DOCX."
                elif file_obj.size > max_size_bytes:
                    errors[field] = "File size must not exceed 10MB."

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "cleaned_data": {
            "center_name": center_name,
            "official_email": official_email,
            "contact_number": contact_number,
            "address": address,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "website": website,
            "description": description,
            "owner_name": owner_name,
            "owner_email": owner_email,
            "owner_phone": owner_phone,
            "password_hash": make_password(password) if password else "",
        },
    }


def send_center_registration_otp(owner_email, ip_address=None, user_agent=""):
    """
    Generate and send an OTP to verify the center owner's email.
    """
    otp_record, otp = create_otp(
        email=owner_email,
        purpose=OTPVerification.Purpose.CENTER_REGISTRATION,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    subject = "Verify Your Edvanto Center Application"
    message = (
        f"Thank you for applying to register your center on Edvanto.\n\n"
        f"Your verification OTP is: {otp}\n\n"
        f"This code will expire in 10 minutes. Please enter it to complete your submission.\n\n"
        f"If you did not request this, please disregard this email."
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[owner_email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.error(f"Failed to send center registration OTP to {owner_email}: {exc}")

    return otp_record, otp


@transaction.atomic
def create_center_application(cleaned_data, files=None, ip_address=None, user_agent=""):
    """
    Create a CenterApplication record in PENDING status and notify admins.
    """
    app = CenterApplication(
        center_name=cleaned_data["center_name"],
        official_email=cleaned_data["official_email"],
        contact_number=cleaned_data["contact_number"],
        address=cleaned_data["address"],
        city=cleaned_data["city"],
        state=cleaned_data["state"],
        postal_code=cleaned_data["postal_code"],
        website=cleaned_data.get("website", ""),
        description=cleaned_data.get("description", ""),
        owner_name=cleaned_data["owner_name"],
        owner_email=cleaned_data["owner_email"],
        owner_phone=cleaned_data["owner_phone"],
        owner_password_hash=cleaned_data["password_hash"],
        status=CenterApplication.Status.PENDING,
    )

    if files:
        if files.get("business_registration_doc"):
            app.business_registration_doc = files["business_registration_doc"]
        if files.get("identity_doc"):
            app.identity_doc = files["identity_doc"]
        if files.get("supporting_doc"):
            app.supporting_doc = files["supporting_doc"]

    app.save()

    # Log security & audit events
    SecurityEvent.objects.create(
        event_type="center_application_submitted",
        severity=SecurityEvent.Severity.INFO,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"application_id": app.id, "center_name": app.center_name, "owner_email": app.owner_email},
    )

    # Notify all active admins & staff
    admins = User.objects.filter(
        is_active=True,
    ).filter(
        Q(is_superuser=True) | Q(role=User.Role.ADMIN) | Q(is_staff=True)
    ).distinct()

    for admin_user in admins:
        create_admin_notification(
            recipient=admin_user,
            title="New Center Registration Application",
            message=f"Center '{app.center_name}' applied for registration. Owner: {app.owner_name} ({app.owner_email}).",
            n_type=Notification.NotificationType.CENTER,
        )

    return app


# ============================================================
# ADMINISTRATOR CENTER MANAGEMENT & APPROVAL WORKFLOW
# ============================================================

@transaction.atomic
def approve_center_application(application, reviewer, admin_notes=""):
    """
    Approve a center application:
    1. Sets status = APPROVED.
    2. Creates or gets Center record and owner User account with role=CENTER.
    3. Associates them and notifies owner.
    Does not grant instant dashboard access until subscription is paid.
    """
    if application.status == CenterApplication.Status.APPROVED and application.center:
        return application.center

    # 1. Create or retrieve User account
    owner_user = User.objects.filter(username=application.owner_email).first()
    if not owner_user:
        name_parts = application.owner_name.strip().split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        owner_user = User(
            username=application.owner_email,
            email=application.owner_email,
            first_name=first_name,
            last_name=last_name,
            phone=application.owner_phone,
            role=User.Role.CENTER,
            is_active=True,
        )
        owner_user.password = application.owner_password_hash
        owner_user.save()
    else:
        owner_user.role = User.Role.CENTER
        owner_user.is_active = True
        owner_user.save(update_fields=["role", "is_active"])

    # 2. Create or associate Center record
    center = Center.objects.filter(email=application.official_email).first()
    if not center:
        center = Center.objects.create(
            name=application.center_name,
            owner=owner_user,
            email=application.official_email,
            contact_number=application.contact_number,
            address=application.address,
            city=application.city,
            state=application.state,
            postal_code=application.postal_code,
            website=application.website,
            description=application.description,
            is_active=True,
            is_suspended=False,
        )
    else:
        center.owner = owner_user
        center.name = application.center_name
        center.contact_number = application.contact_number
        center.address = application.address
        center.city = application.city
        center.state = application.state
        center.postal_code = application.postal_code
        center.website = application.website
        center.description = application.description
        center.is_active = True
        center.is_suspended = False
        center.save()

    # 3. Update application status
    application.status = CenterApplication.Status.APPROVED
    application.center = center
    application.user = owner_user
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    if admin_notes:
        application.admin_notes = admin_notes
    application.save()

    # 4. Notify the center owner
    notif = Notification.objects.create(
        recipient=owner_user,
        title="Center Application Approved",
        message=(
            f"Congratulations! Your center application for '{center.name}' has been approved by Edvanto. "
            f"Please subscribe to a plan to activate your Center Dashboard."
        ),
        notification_type=Notification.NotificationType.CENTER,
    )
    NotificationDelivery.objects.create(
        notification=notif,
        channel=NotificationDelivery.Channel.IN_APP,
        status=NotificationDelivery.Status.SENT,
        sent_at=timezone.now(),
    )

    # 5. Audit Log
    AuditLog.objects.create(
        actor=reviewer,
        action="approve_center_application",
        model_name="CenterApplication",
        object_id=str(application.id),
        changes={"center_id": center.id, "owner_id": owner_user.id, "status": "approved"},
    )

    return center


@transaction.atomic
def reject_center_application(application, reviewer, reason=""):
    """
    Reject a center application with a recorded reason and notify applicant if possible.
    """
    application.status = CenterApplication.Status.REJECTED
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.admin_notes = reason
    application.save()

    AuditLog.objects.create(
        actor=reviewer,
        action="reject_center_application",
        model_name="CenterApplication",
        object_id=str(application.id),
        changes={"reason": reason, "status": "rejected"},
    )

    return application


@transaction.atomic
def create_center_by_admin(
    *,
    name,
    email,
    contact_number,
    address,
    city="",
    state="",
    postal_code="",
    website="",
    description="",
    owner_name="",
    owner_email="",
    owner_phone="",
    owner_password="",
    creator=None,
):
    """
    Create a Center and associated owner account manually by an administrator.
    """
    owner_email = normalize_email(owner_email)
    owner_user = None

    if owner_email:
        owner_user = User.objects.filter(username=owner_email).first()
        if not owner_user:
            name_parts = owner_name.strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            owner_user = User(
                username=owner_email,
                email=owner_email,
                first_name=first_name,
                last_name=last_name,
                phone=owner_phone,
                role=User.Role.CENTER,
                is_active=True,
            )
            if owner_password:
                owner_user.set_password(owner_password)
            else:
                owner_user.set_unusable_password()
            owner_user.save()
        else:
            owner_user.role = User.Role.CENTER
            owner_user.is_active = True
            owner_user.save(update_fields=["role", "is_active"])

    center = Center.objects.create(
        name=name.strip(),
        owner=owner_user,
        email=normalize_email(email),
        contact_number=contact_number.strip(),
        address=address.strip(),
        city=city.strip(),
        state=state.strip(),
        postal_code=postal_code.strip(),
        website=website.strip(),
        description=description.strip(),
        is_active=True,
        is_suspended=False,
    )

    AuditLog.objects.create(
        actor=creator,
        action="admin_create_center",
        model_name="Center",
        object_id=str(center.id),
        changes={"name": center.name, "owner": owner_user.username if owner_user else None},
    )

    return center


@transaction.atomic
def toggle_center_suspension(center, actor, reason=""):
    """
    Suspend or unsuspend a center.
    """
    center.is_suspended = not center.is_suspended
    center.save(update_fields=["is_suspended", "updated_at"])

    action = "suspend_center" if center.is_suspended else "unsuspend_center"
    AuditLog.objects.create(
        actor=actor,
        action=action,
        model_name="Center",
        object_id=str(center.id),
        changes={"is_suspended": center.is_suspended, "reason": reason},
    )

    if center.owner:
        msg = (
            f"Your center '{center.name}' has been suspended. Please contact administrator."
            if center.is_suspended
            else f"Your center '{center.name}' has been unsuspended."
        )
        notif = Notification.objects.create(
            recipient=center.owner,
            title="Center Status Update",
            message=msg,
            notification_type=Notification.NotificationType.CENTER,
        )
        NotificationDelivery.objects.create(
            notification=notif,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.SENT,
            sent_at=timezone.now(),
        )

    return center


# ============================================================
# SUBSCRIPTION & PAYMENT WORKFLOW
# ============================================================

def ensure_default_subscription_plans():
    """
    Ensure the standard 6-Month and Annual plans exist and are active.
    """
    plans = [
        {"name": "Six-Month Plan", "duration_months": 6, "price": Decimal("15000.00"), "description": "Access to Edvanto Center Management for 6 calendar months."},
        {"name": "Annual Plan", "duration_months": 12, "price": Decimal("25000.00"), "description": "Full access to Edvanto Center Management for 12 calendar months with priority support."},
    ]
    created_any = False
    for p in plans:
        plan, created = CenterSubscriptionPlan.objects.get_or_create(
            duration_months=p["duration_months"],
            defaults={"name": p["name"], "price": p["price"], "description": p["description"], "is_active": True},
        )
        if created:
            created_any = True
    return created_any


@transaction.atomic
def create_center_subscription_order(*, center, plan):
    """
    Create a pending subscription and initialize payment transaction with Razorpay.
    """
    if center.is_suspended:
        raise ValueError("Cannot subscribe a suspended center.")

    now = timezone.now()

    # Create or reuse existing pending subscription for this center and plan
    subscription = CenterSubscription.objects.filter(
        center=center,
        plan=plan,
        status=CenterSubscription.Status.PENDING_PAYMENT,
    ).first()

    if not subscription:
        subscription = CenterSubscription.objects.create(
            center=center,
            plan=plan,
            status=CenterSubscription.Status.PENDING_PAYMENT,
        )

    amount = plan.price
    amount_in_paise = int(amount * 100)

    client = get_razorpay_client()
    razorpay_order_id = ""
    gateway_configured = False

    if client:
        receipt = f"SUB-{now:%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"
        razorpay_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {
                "center_id": str(center.id),
                "center_name": str(center.name)[:40],
                "plan_id": str(plan.id),
                "plan_name": str(plan.name)[:40],
                "subscription_id": str(subscription.id),
            },
        }
        try:
            rp_order = client.order.create(data=razorpay_data)
            razorpay_order_id = rp_order["id"]
            gateway_configured = True
        except Exception as exc:
            logger.error(f"Failed to create Razorpay subscription order: {exc}")
            raise ValueError(f"Gateway error: {exc}")

    payment = CenterSubscriptionPayment.objects.create(
        subscription=subscription,
        amount=amount,
        payment_method="razorpay",
        razorpay_order_id=razorpay_order_id,
        status=CenterSubscriptionPayment.Status.PENDING,
        metadata={
            "plan_name": plan.name,
            "duration_months": plan.duration_months,
            "gateway_configured": gateway_configured,
        },
    )

    return subscription, payment, gateway_configured


@transaction.atomic
def verify_center_subscription_payment(
    *,
    razorpay_order_id,
    razorpay_payment_id,
    razorpay_signature,
    is_webhook=False,
):
    """
    Verify payment signature and activate the center's subscription for exact calendar months.
    Idempotent: Re-verifying an already active subscription succeeds cleanly without duplicate activation.
    """
    payment = (
        CenterSubscriptionPayment.objects
        .select_for_update()
        .filter(razorpay_order_id=razorpay_order_id)
        .order_by("-created_at")
        .first()
    )

    if not payment:
        raise ValueError(f"No subscription payment record found for order ID: {razorpay_order_id}")

    subscription = payment.subscription
    center = subscription.center

    # Idempotency check: Already activated?
    if payment.status == CenterSubscriptionPayment.Status.SUCCESS and subscription.status == CenterSubscription.Status.ACTIVE:
        return subscription, payment

    # Signature verification
    if not is_webhook:
        client = get_razorpay_client()
        if not client:
            raise ValueError("Razorpay client is not configured.")

        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            })
        except Exception as exc:
            payment.status = CenterSubscriptionPayment.Status.FAILED
            payment.error_message = f"Signature verification failed: {exc}"
            payment.save(update_fields=["status", "error_message"])
            subscription.status = CenterSubscription.Status.FAILED
            subscription.save(update_fields=["status", "updated_at"])
            raise ValueError("Payment verification failed. Invalid signature.")

    # Successful payment: Record details
    now = timezone.now()
    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.status = CenterSubscriptionPayment.Status.SUCCESS
    payment.paid_at = now
    payment.save(update_fields=["razorpay_payment_id", "razorpay_signature", "status", "paid_at"])

    # Activate Subscription with exact calendar months
    # Check if there is an existing active subscription to extend (renewal)
    existing_active = (
        CenterSubscription.objects
        .filter(center=center, status=CenterSubscription.Status.ACTIVE, end_date__gt=now)
        .exclude(pk=subscription.pk)
        .order_by("-end_date")
        .first()
    )

    if existing_active and existing_active.end_date:
        start_date = existing_active.end_date
    else:
        start_date = now

    end_date = start_date + relativedelta(months=subscription.plan.duration_months)

    subscription.status = CenterSubscription.Status.ACTIVE
    subscription.start_date = start_date
    subscription.end_date = end_date
    subscription.save(update_fields=["status", "start_date", "end_date", "updated_at"])

    # Notify Center Owner
    if center.owner:
        notif = Notification.objects.create(
            recipient=center.owner,
            title="Subscription Activated",
            message=(
                f"Your subscription to {subscription.plan.name} is active! "
                f"Valid until {end_date.strftime('%d %B %Y')}."
            ),
            notification_type=Notification.NotificationType.SUBSCRIPTION,
        )
        NotificationDelivery.objects.create(
            notification=notif,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.SENT,
            sent_at=now,
        )

    # Notify Administrators
    admins = User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(role=User.Role.ADMIN)
    ).distinct()
    for admin_user in admins:
        create_admin_notification(
            recipient=admin_user,
            title="Center Subscription Activated",
            message=f"Center '{center.name}' paid ₹{payment.amount} for {subscription.plan.name}.",
            n_type=Notification.NotificationType.SUBSCRIPTION,
        )

    # Audit Log
    AuditLog.objects.create(
        actor=center.owner,
        action="activate_center_subscription",
        model_name="CenterSubscription",
        object_id=str(subscription.id),
        changes={
            "center": center.name,
            "plan": subscription.plan.name,
            "amount": str(payment.amount),
            "end_date": end_date.isoformat(),
        },
    )

    return subscription, payment


@transaction.atomic
def record_manual_subscription_activation(*, center, plan, actor, notes=""):
    """
    Allow administrators to manually activate or renew a subscription (e.g. for offline bank transfer).
    """
    now = timezone.now()
    existing_active = (
        CenterSubscription.objects
        .filter(center=center, status=CenterSubscription.Status.ACTIVE, end_date__gt=now)
        .order_by("-end_date")
        .first()
    )

    if existing_active and existing_active.end_date:
        start_date = existing_active.end_date
    else:
        start_date = now

    end_date = start_date + relativedelta(months=plan.duration_months)

    subscription = CenterSubscription.objects.create(
        center=center,
        plan=plan,
        status=CenterSubscription.Status.ACTIVE,
        start_date=start_date,
        end_date=end_date,
    )

    payment = CenterSubscriptionPayment.objects.create(
        subscription=subscription,
        amount=plan.price,
        payment_method="offline_manual",
        status=CenterSubscriptionPayment.Status.SUCCESS,
        paid_at=now,
        metadata={"activated_by": actor.username, "notes": notes},
    )

    AuditLog.objects.create(
        actor=actor,
        action="manual_activate_subscription",
        model_name="CenterSubscription",
        object_id=str(subscription.id),
        changes={"center": center.name, "plan": plan.name, "notes": notes},
    )

    return subscription, payment


# ============================================================
# INSTRUCTOR & COURSE ASSIGNMENT
# ============================================================

@transaction.atomic
def add_instructor_to_center(*, center, first_name, last_name, email, phone, specialization="", password="", profile_photo=None):
    """
    Register or associate an instructor with a center.
    """
    email = normalize_email(email)

    user = User.objects.filter(username=email).first()
    if not user:
        user = User(
            username=email,
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone.strip(),
            role=User.Role.INSTRUCTOR,
            is_active=True,
        )
        if profile_photo:
            user.profile_photo = profile_photo
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
    else:
        # Existing account: verify not superuser or admin
        if user.is_superuser or user.role == User.Role.ADMIN:
            raise ValueError("Privileged platform accounts cannot be added as center instructors.")
        user.role = User.Role.INSTRUCTOR
        user.is_active = True
        user.save(update_fields=["role", "is_active"])

    membership, created = CenterInstructor.objects.get_or_create(
        center=center,
        instructor=user,
        defaults={
            "specialization": specialization.strip(),
            "is_active": True,
        },
    )
    if not created and not membership.is_active:
        membership.is_active = True
        membership.specialization = specialization.strip()
        membership.save(update_fields=["is_active", "specialization", "updated_at"])

    # Audit Log
    AuditLog.objects.create(
        actor=center.owner,
        action="add_center_instructor",
        model_name="CenterInstructor",
        object_id=str(membership.id),
        changes={"center": center.name, "instructor": user.username},
    )

    return membership


@transaction.atomic
def assign_course_instructor(*, course, instructor, center, actor):
    """
    Assign an eligible center instructor to a center course.
    """
    if course.center != center:
        raise ValueError("Cannot assign instructor to a course belonging to another center.")

    if not CenterInstructor.objects.filter(center=center, instructor=instructor, is_active=True).exists():
        raise ValueError("Selected instructor is not an active instructor in your center.")

    old_instructor = course.instructor
    course.instructor = instructor
    course.save(update_fields=["instructor", "updated_at"])

    # Notify new instructor
    notif = Notification.objects.create(
        recipient=instructor,
        title="Assigned to Course",
        message=f"You have been assigned as the instructor for course: '{course.title}' at '{center.name}'.",
        notification_type=Notification.NotificationType.COURSE,
    )
    NotificationDelivery.objects.create(
        notification=notif,
        channel=NotificationDelivery.Channel.IN_APP,
        status=NotificationDelivery.Status.SENT,
        sent_at=timezone.now(),
    )

    # Audit Log
    AuditLog.objects.create(
        actor=actor,
        action="assign_course_instructor",
        model_name="Course",
        object_id=str(course.id),
        changes={
            "course": course.title,
            "old_instructor": old_instructor.username if old_instructor else None,
            "new_instructor": instructor.username,
        },
    )

    return course

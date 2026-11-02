from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from ..models import *

from .enrollment import *


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _get_course_amount(course):
    """
    Return the effective course price.
    Discounted price is used when available.
    """

    if (
        course.discounted_price is not None
        and course.discounted_price > 0
    ):
        return course.discounted_price

    return course.price


def _create_notification(
    recipient,
    title,
    message,
):
    """
    Create an in-app notification.

    Email delivery will be connected later through the
    centralized notification system.
    """

    return Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.PAYMENT,
    )


def _create_invoice(
    order,
    paid=False,
):
    """
    Create the existing invoice record for an order.

    An invoice is created only once.
    """
    invoice_number = (
        f"INV-{timezone.now():%Y%m%d%H%M%S}-"
        f"{uuid4().hex[:8].upper()}"
    )
    invoice, created = Invoice.objects.get_or_create(
        order=order,
        defaults={
            "student": order.student,
            "course": order.course,
            "amount": order.total_amount,
            "tax_amount": 0,
            "total_amount": order.total_amount,
            "invoice_number": invoice_number,
            "status": (
                Invoice.Status.PAID
                if paid
                else Invoice.Status.ISSUED
            ),
            "issued_at": timezone.now(),
            "paid_at": (
                timezone.now()
                if paid
                else None
            ),
        },
    )

    if not created and paid:
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(
            update_fields=[
                "status",
                "paid_at",
                "updated_at",
            ]
        )

    return invoice


# ============================================================
# TEST PAYMENT
# ============================================================

@transaction.atomic
def create_test_payment(
    *,
    student,
    course,
):
    """
    Create and immediately complete a development/test payment.

    This is NOT a real payment gateway.

    Flow:
        Order → PaymentTransaction → Enrollment → Access
    """

    if student.role != User.Role.STUDENT:
        raise ValueError(
            "Only students can make course payments."
        )

    if course.status != Course.Status.PUBLISHED:
        raise ValueError(
            "This course is not available for purchase."
        )

    # Restriction: A student can only be enrolled in one course at a time
    other_enrollment = get_student_active_or_pending_enrollment(student, exclude_course=course)
    if other_enrollment:
        raise ValueError(
            f"You are already enrolled in '{other_enrollment.course.title}'. "
            "Edvanto permits enrollment in only one course at a time. Please complete your current course first."
        )

    existing_enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            course=course,
        )
        .first()
    )

    if existing_enrollment:
        raise ValueError(
            "You already have an enrollment for this course."
        )

    amount = _get_course_amount(course)

    if amount is None or amount <= 0:
        raise ValueError(
            "This course does not have a valid price."
        )

    order = Order.objects.create(
        student=student,
        course=course,
        order_number=(
            f"TEST-{timezone.now():%Y%m%d%H%M%S}-"
            f"{uuid4().hex[:8].upper()}"
        ),
        total_amount=amount,
        payment_plan=Order.PaymentPlan.FULL,
        payment_method=Order.PaymentMethod.TEST,
        status=Order.Status.CREATED,
    )

    payment_transaction = PaymentTransaction.objects.create(
        order=order,
        amount=amount,
        status=PaymentTransaction.Status.SUCCESS,
        paid_at=timezone.now(),
        metadata={
            "payment_method": Order.PaymentMethod.TEST,
            "test_payment": True,
        },
    )

    order.status = Order.Status.PAID
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment, _ = create_enrollment(
        student,
        course,
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment could not be created."
        )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PAID
    )

    if course.requires_instructor_approval:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.PENDING
        )
    else:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.ACCEPTED
        )
        enrollment.accepted_at = timezone.now()

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    if (
        enrollment.approval_status
        == Enrollment.ApprovalStatus.ACCEPTED
    ):
        initialize_learning_progress(
            enrollment
        )

    _create_invoice(
        order,
        paid=True,
    )

    _create_notification(
        recipient=student,
        title="Test payment successful",
        message=(
            f"Your test payment for "
            f"{course.title} was successful."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# OFFLINE PAYMENT REQUEST
# ============================================================

@transaction.atomic
def create_offline_payment_request(
    *,
    student,
    course,
    payment_mode="UPI",
    transaction_reference="",
    payment_date=None,
    notes="",
):
    """
    Create an offline payment request with student-provided transaction details.

    No payment is considered successful at this stage.

    Flow:
        Order CREATED
        PaymentTransaction CREATED
        Enrollment PENDING
    """

    if student.role != User.Role.STUDENT:
        raise ValueError(
            "Only students can request course enrollment."
        )

    if course.status != Course.Status.PUBLISHED:
        raise ValueError(
            "This course is not available for enrollment."
        )

    # Restriction: A student can only be enrolled in one course at a time
    other_enrollment = get_student_active_or_pending_enrollment(student, exclude_course=course)
    if other_enrollment:
        raise ValueError(
            f"You are already enrolled in '{other_enrollment.course.title}'. "
            "Edvanto permits enrollment in only one course at a time. Please complete your current course first."
        )

    existing_enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            course=course,
        )
        .first()
    )

    if existing_enrollment:
        if existing_enrollment.payment_status == Enrollment.PaymentStatus.PAID:
            raise ValueError(
                "You are already enrolled in this course."
            )
        elif existing_enrollment.approval_status == Enrollment.ApprovalStatus.PENDING:
            raise ValueError(
                "You already have a pending offline payment request for this course. "
                "Please wait for administrator verification."
            )

    amount = _get_course_amount(course)

    if amount is None or amount <= 0:
        raise ValueError(
            "This course does not have a valid price."
        )

    order = Order.objects.create(
        student=student,
        course=course,
        order_number=(
            f"OFF-{timezone.now():%Y%m%d%H%M%S}-"
            f"{uuid4().hex[:8].upper()}"
        ),
        total_amount=amount,
        payment_plan=Order.PaymentPlan.FULL,
        payment_method=Order.PaymentMethod.OFFLINE,
        status=Order.Status.CREATED,
    )

    clean_ref = (transaction_reference or "").strip()
    clean_notes = (notes or "").strip()
    clean_mode = (payment_mode or "UPI").strip()
    clean_date = str(payment_date) if payment_date else timezone.now().strftime("%Y-%m-%d")

    metadata = {
        "payment_method": Order.PaymentMethod.OFFLINE,
        "offline_request": True,
        "payment_mode": clean_mode,
        "transaction_reference": clean_ref,
        "payment_date": clean_date,
        "notes": clean_notes,
    }

    payment_transaction = PaymentTransaction.objects.create(
        order=order,
        amount=amount,
        status=PaymentTransaction.Status.CREATED,
        metadata=metadata,
    )

    enrollment, _ = create_enrollment(
        student,
        course,
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment could not be created."
        )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PENDING
    )

    enrollment.approval_status = (
        Enrollment.ApprovalStatus.PENDING
    )

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
        ]
    )

    _create_invoice(
        order,
        paid=False,
    )

    ref_info = f" (Ref: {clean_ref})" if clean_ref else ""
    _create_notification(
        recipient=student,
        title="Offline payment request submitted",
        message=(
            f"Your offline payment request for "
            f"{course.title}{ref_info} has been submitted "
            f"and is waiting for admin verification."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# ADMIN APPROVE OFFLINE PAYMENT
# ============================================================

@transaction.atomic
def approve_offline_payment(
    *,
    order,
    approved_by=None,
):
    """
    Approve an offline payment request.

    Approval means:
        Payment confirmed
        Order paid
        Enrollment accepted
        Learning access initialized
    """

    if order.payment_method != Order.PaymentMethod.OFFLINE:
        raise ValueError(
            "This order is not an offline payment request."
        )

    if order.status == Order.Status.PAID:
        raise ValueError(
            "This payment has already been approved."
        )

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .filter(
            student=order.student,
            course=order.course,
        )
        .first()
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment for this order was not found."
        )

    payment_transaction = (
        order.transactions
        .select_for_update()
        .filter(
            status=PaymentTransaction.Status.CREATED
        )
        .order_by("-created_at")
        .first()
    )

    if payment_transaction is None:
        raise ValueError(
            "Pending payment transaction was not found."
        )

    now = timezone.now()

    payment_transaction.status = (
        PaymentTransaction.Status.SUCCESS
    )
    payment_transaction.paid_at = now
    payment_transaction.metadata = {
        **payment_transaction.metadata,
        "approved_by": (
            approved_by.pk
            if approved_by
            else None
        ),
        "approved_at": now.isoformat(),
    }

    payment_transaction.save(
        update_fields=[
            "status",
            "paid_at",
            "metadata",
        ]
    )

    order.status = Order.Status.PAID
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PAID
    )
    enrollment.approval_status = (
        Enrollment.ApprovalStatus.ACCEPTED
    )
    enrollment.accepted_at = now

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    initialize_learning_progress(
        enrollment
    )

    _create_invoice(
        order,
        paid=True,
    )

    _create_notification(
        recipient=order.student,
        title="Payment approved",
        message=(
            f"Your offline payment for "
            f"{order.course.title} has been approved. "
            f"Your course access is now active."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# ADMIN REJECT OFFLINE PAYMENT
# ============================================================

@transaction.atomic
def reject_offline_payment(
    *,
    order,
    rejected_by=None,
    reason="",
):
    """
    Reject an offline payment request.
    """

    if order.payment_method != Order.PaymentMethod.OFFLINE:
        raise ValueError(
            "This order is not an offline payment request."
        )

    if order.status == Order.Status.PAID:
        raise ValueError(
            "A paid order cannot be rejected."
        )

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .filter(
            student=order.student,
            course=order.course,
        )
        .first()
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment for this order was not found."
        )

    payment_transaction = (
        order.transactions
        .select_for_update()
        .filter(
            status=PaymentTransaction.Status.CREATED
        )
        .order_by("-created_at")
        .first()
    )

    now = timezone.now()

    if payment_transaction:
        payment_transaction.status = (
            PaymentTransaction.Status.FAILED
        )
        payment_transaction.failure_reason = (
            reason or "Offline payment request rejected."
        )
        payment_transaction.metadata = {
            **payment_transaction.metadata,
            "rejected_by": (
                rejected_by.pk
                if rejected_by
                else None
            ),
            "rejected_at": now.isoformat(),
        }

        payment_transaction.save(
            update_fields=[
                "status",
                "failure_reason",
                "metadata",
            ]
        )

    order.status = Order.Status.CANCELLED
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.FAILED
    )
    enrollment.approval_status = (
        Enrollment.ApprovalStatus.REJECTED
    )

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
        ]
    )

    _create_notification(
        recipient=order.student,
        title="Offline payment request rejected",
        message=(
            f"Your offline payment request for "
            f"{order.course.title} was rejected."
            + (
                f" Reason: {reason}"
                if reason
                else ""
            )
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# RAZORPAY PAYMENT GATEWAY
# ============================================================

def get_razorpay_client():
    """
    Initialize and return the Razorpay Client instance if credentials exist.
    """
    from django.conf import settings
    key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if key_id and key_secret:
        try:
            import razorpay
            return razorpay.Client(auth=(key_id, key_secret))
        except ImportError:
            return None
    return None


@transaction.atomic
def create_razorpay_order(
    *,
    student,
    course,
):
    """
    Create a Razorpay order with the gateway and record pending Order & Transaction.
    Returns (order, payment_transaction, razorpay_order_dict).
    """
    if student.role != User.Role.STUDENT:
        raise ValueError("Only students can purchase courses.")

    if course.status != Course.Status.PUBLISHED:
        raise ValueError("This course is not available for purchase.")

    # Restriction: A student can only be enrolled in one course at a time
    other_enrollment = get_student_active_or_pending_enrollment(student, exclude_course=course)
    if other_enrollment:
        raise ValueError(
            f"You are already enrolled in '{other_enrollment.course.title}'. "
            "Edvanto permits enrollment in only one course at a time. Please complete your current course first."
        )

    existing_enrollment = (
        Enrollment.objects
        .filter(student=student, course=course)
        .first()
    )
    if existing_enrollment and existing_enrollment.payment_status == Enrollment.PaymentStatus.PAID:
        raise ValueError("You already have an active enrollment for this course.")

    amount = _get_course_amount(course)
    if amount is None or amount <= 0:
        raise ValueError("This course does not have a valid price.")

    amount_in_paise = int(amount * 100)
    client = get_razorpay_client()
    if not client:
        raise ValueError("Razorpay credentials are not configured in settings. Please contact the administrator.")

    receipt = f"RCPT-{timezone.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"
    razorpay_data = {
        "amount": amount_in_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "course_id": str(course.id),
            "course_title": str(course.title)[:40],
            "student_id": str(student.id),
            "student_email": str(student.email),
        },
    }

    try:
        rp_order = client.order.create(data=razorpay_data)
        razorpay_order_id = rp_order["id"]
    except Exception as exc:
        raise ValueError(f"Failed to create Razorpay order: {exc}")

    order = Order.objects.create(
        student=student,
        course=course,
        order_number=f"RZP-{timezone.now():%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}",
        total_amount=amount,
        payment_plan=Order.PaymentPlan.FULL,
        payment_method=Order.PaymentMethod.RAZORPAY,
        status=Order.Status.CREATED,
    )

    payment_transaction = PaymentTransaction.objects.create(
        order=order,
        amount=amount,
        razorpay_order_id=razorpay_order_id,
        status=PaymentTransaction.Status.CREATED,
        metadata={
            "payment_method": Order.PaymentMethod.RAZORPAY,
            "razorpay_order_id": razorpay_order_id,
            "currency": "INR",
            "receipt": receipt,
        },
    )

    return order, payment_transaction, rp_order


@transaction.atomic
def verify_and_complete_razorpay_payment(
    *,
    razorpay_order_id,
    razorpay_payment_id,
    razorpay_signature="",
    student=None,
    is_webhook=False,
):
    """
    Verify Razorpay payment signature and complete enrollment.
    """
    payment_transaction = (
        PaymentTransaction.objects
        .select_for_update()
        .filter(razorpay_order_id=razorpay_order_id)
        .order_by("-created_at")
        .first()
    )

    if not payment_transaction:
        raise ValueError(f"No payment order record found for ID {razorpay_order_id}.")

    order = payment_transaction.order
    if student and order.student != student and not student.is_staff:
        raise ValueError("Unauthorized payment verification request.")

    if order.status == Order.Status.PAID:
        enrollment = Enrollment.objects.filter(student=order.student, course=order.course).first()
        return order, payment_transaction, enrollment

    # Verify signature if not verified beforehand by webhook signature
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
            payment_transaction.status = PaymentTransaction.Status.FAILED
            payment_transaction.failure_reason = f"Signature verification error: {exc}"
            payment_transaction.save(update_fields=["status", "failure_reason"])
            order.status = Order.Status.FAILED
            order.save(update_fields=["status", "updated_at"])
            raise ValueError("Payment signature verification failed. Please try again or contact support.")

    now = timezone.now()
    payment_transaction.razorpay_payment_id = razorpay_payment_id
    if razorpay_signature:
        payment_transaction.razorpay_signature = razorpay_signature
    payment_transaction.status = PaymentTransaction.Status.SUCCESS
    payment_transaction.paid_at = now
    payment_transaction.metadata = {
        **payment_transaction.metadata,
        "razorpay_payment_id": razorpay_payment_id,
        "verified_at": now.isoformat(),
        "via_webhook": is_webhook,
    }
    payment_transaction.save(
        update_fields=[
            "razorpay_payment_id",
            "razorpay_signature",
            "status",
            "paid_at",
            "metadata",
        ]
    )

    order.status = Order.Status.PAID
    order.save(update_fields=["status", "updated_at"])

    enrollment, _ = create_enrollment(order.student, order.course)
    if enrollment is None:
        raise ValueError("Enrollment could not be created.")

    enrollment.payment_status = Enrollment.PaymentStatus.PAID
    if order.course.requires_instructor_approval:
        enrollment.approval_status = Enrollment.ApprovalStatus.PENDING
    else:
        enrollment.approval_status = Enrollment.ApprovalStatus.ACCEPTED
        enrollment.accepted_at = now

    enrollment.save(update_fields=["payment_status", "approval_status", "accepted_at"])

    if enrollment.approval_status == Enrollment.ApprovalStatus.ACCEPTED:
        initialize_learning_progress(enrollment)

    _create_invoice(order, paid=True)

    _create_notification(
        recipient=order.student,
        title="Payment Successful",
        message=f"Your payment for {order.course.title} was completed successfully. Access is active!",
    )

    return order, payment_transaction, enrollment

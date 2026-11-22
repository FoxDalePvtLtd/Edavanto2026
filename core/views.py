from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from django.core.mail import send_mail
from django.db import IntegrityError
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import datetime, timedelta 
from .services.learning import *
from .services.enrollment import *
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .services.payments import *
from .auth_services import (
    OTP_EXPIRY_MINUTES,
    create_otp,
    normalize_email, 
    verify_otp,
    create_student_from_registration,
)

from .models import *
from decimal import Decimal
from core.services.material_crypto import decrypt_bytes
from core.services.doc_converter import convert_material_to_note_html
from core.forms import CareerConsultationForm, StudentDoubtThreadForm, DoubtMessageForm

from .registration_services import (
    validate_student_registration,
)

from core.services.notification import create_admin_notification


User = get_user_model()




def home(request):
    selected_category = request.GET.get("category", "").strip()

    courses_queryset = (
        Course.objects
        .filter(status=Course.Status.PUBLISHED)
        .select_related("instructor", "center")
    )

    # Filter by category if one is selected and it's not "all"
    if selected_category and selected_category != "all":
        courses_queryset = courses_queryset.filter(category=selected_category)
        
    courses_queryset = courses_queryset.order_by("-created_at")[:6]

    return render(
        request, 
        "home.html", 
        {
            "courses": courses_queryset,
            "selected_category": selected_category,
        },
    )




# Courses 
def courses(request):
    courses_queryset = (
        Course.objects
        .filter(
            status=Course.Status.PUBLISHED
        )
        .select_related(
            "instructor",
            "center",
        )
        .order_by("-created_at")
    )

    return render(
        request,
        "courses.html",
        {
            "courses": courses_queryset,
        },
    )


def about(request):
    return render(request, "about.html")


def contact(request):
    return render(request, "contact.html")


# ============================================================
# STUDENT REGISTRATION
# ============================================================

def student_register(request):

    print("\n" + "=" * 70)
    print("[EDVANTO REGISTER] student_register() CALLED")
    print(f"[EDVANTO REGISTER] METHOD: {request.method}")
    print("=" * 70)

    if request.method == "GET":
        print("[EDVANTO REGISTER] GET request -> rendering sign-in.html")
        return render(
            request,
            "sign-in.html",
            {"registration_data": {}},
        )

    if request.method != "POST":
        print(
            f"[EDVANTO REGISTER] Unexpected method: {request.method}"
        )
        return redirect("core:sign_in")

    print("[EDVANTO REGISTER] POST received successfully")

    # ---------------------------------------------------------
    # HONEYPOT
    # ---------------------------------------------------------

    honeypot = request.POST.get("website", "").strip()

    print(f"[EDVANTO REGISTER] Honeypot value: {repr(honeypot)}")

    if honeypot:
        print("[EDVANTO REGISTER] STOP -> honeypot triggered")
        return redirect("core:sign_in")

    # ---------------------------------------------------------
    # FORM DATA
    # ---------------------------------------------------------

    full_name = request.POST.get("full_name", "").strip()
    email = normalize_email(request.POST.get("email", ""))
    phone = request.POST.get("phone", "").strip()
    password = request.POST.get("password", "")
    confirm_password = request.POST.get("confirm_password", "")
    terms = request.POST.get("terms")

    print("[EDVANTO REGISTER] Form data received:")
    print(f"  full_name = {repr(full_name)}")
    print(f"  email     = {repr(email)}")
    print(f"  phone     = {repr(phone)}")
    print(f"  password  = {'RECEIVED' if password else 'EMPTY'}")
    print(
        f"  confirm   = {'RECEIVED' if confirm_password else 'EMPTY'}"
    )
    print(f"  terms     = {repr(terms)}")

    # ---------------------------------------------------------
    # TERMS
    # ---------------------------------------------------------

    if not terms:
        print("[EDVANTO REGISTER] STOP -> terms not accepted")

        return render(
            request,
            "sign-in.html",
            {
                "registration_data": {
                    "full_name": full_name,
                    "email": email,
                    "phone": phone,
                },
                "registration_errors": {
                    "terms": "Please accept the terms and privacy policy.",
                },
            },
            status=400,
        )

    print("[EDVANTO REGISTER] Terms accepted")

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    print("[EDVANTO REGISTER] Running validation...")

    result = validate_student_registration(
        full_name=full_name,
        email=email,
        phone=phone,
        password=password,
        confirm_password=confirm_password,
    )

    print(
        f"[EDVANTO REGISTER] Validation errors: "
        f"{result['errors']}"
    )

    if result["errors"]:

        print("[EDVANTO REGISTER] STOP -> validation failed")

        field_errors = {}
        for error in result["errors"]:
            print(f"  ERROR: {error}")
            lowered = error.lower()

            if "email" in lowered:
                field_errors["email"] = error
            elif "password" in lowered or "passwords" in lowered:
                field_errors["password"] = error
                if "match" in lowered:
                    field_errors["confirm_password"] = error
            elif "phone" in lowered:
                field_errors["phone"] = error
            elif "name" in lowered:
                field_errors["full_name"] = error
            else:
                field_errors.setdefault("form", error)

        return render(
            request,
            "sign-in.html",
            {
                "registration_data": {
                    "full_name": full_name,
                    "email": email,
                    "phone": phone,
                },
                "registration_errors": field_errors,
            },
            status=400,
        )

    print("[EDVANTO REGISTER] Validation PASSED")

    # ---------------------------------------------------------
    # CREATE OTP
    # ---------------------------------------------------------

    print("[EDVANTO REGISTER] Creating OTP...")

    try:

        otp_record, otp = create_otp(
            email=result["email"],
            purpose=OTPVerification.Purpose.REGISTRATION,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get(
                "HTTP_USER_AGENT",
                "",
            ),
        )

        print("[EDVANTO REGISTER] OTP CREATED")
        print(f"[EDVANTO REGISTER] OTP: {otp}")
        print(
            f"[EDVANTO REGISTER] OTP record ID: "
            f"{otp_record.id}"
        )

    except ValueError as exc:

        print(
            "[EDVANTO REGISTER] STOP -> OTP creation failed"
        )
        print(f"[EDVANTO REGISTER] OTP ERROR: {exc}")

        messages.error(request, str(exc))

        return redirect("core:sign_in")

    except Exception as exc:

        print(
            "[EDVANTO REGISTER] STOP -> unexpected OTP error"
        )
        print(
            f"[EDVANTO REGISTER] OTP EXCEPTION: "
            f"{type(exc).__name__}: {exc}"
        )

        raise

    # ---------------------------------------------------------
    # STORE PENDING REGISTRATION
    # ---------------------------------------------------------

    print("[EDVANTO REGISTER] Storing pending registration")

    request.session["pending_registration"] = {
        "full_name": result["full_name"],
        "email": result["email"],
        "phone": result["phone"],
        "password_hash": result["password_hash"],
    }

    request.session["pending_registration_created_at"] = (
        timezone.now().isoformat()
    )

    request.session.modified = True

    print("[EDVANTO REGISTER] Session data stored")
    print(
        "[EDVANTO REGISTER] pending_registration exists:",
        "pending_registration" in request.session,
    )

    # ---------------------------------------------------------
    # SEND OTP
    # ---------------------------------------------------------

    print("[EDVANTO REGISTER] Sending OTP email...")

    try:

        send_mail(
            subject="Your Edvanto verification code",
            message=(
                f"Hello {result['full_name']},\n\n"
                f"Your Edvanto verification code is: {otp}\n\n"
                f"This code will expire in "
                f"{OTP_EXPIRY_MINUTES} minutes.\n\n"
                f"If you did not request this registration, "
                f"you can safely ignore this email.\n\n"
                f"Regards,\n"
                f"Edvanto"
            ),
            from_email=None,
            recipient_list=[result["email"]],
            fail_silently=False,
        )

        print("[EDVANTO REGISTER] EMAIL SEND COMPLETED")

    except Exception as exc:

        print(
            "[EDVANTO REGISTER] STOP -> EMAIL SEND FAILED"
        )
        print(
            f"[EDVANTO REGISTER] EMAIL EXCEPTION: "
            f"{type(exc).__name__}: {exc}"
        )

        request.session.pop(
            "pending_registration",
            None,
        )

        request.session.pop(
            "pending_registration_created_at",
            None,
        )

        messages.error(
            request,
            "We could not send the verification email. "
            "Please try again."
        )

        return redirect("core:sign_in")

    # ---------------------------------------------------------
    # FINAL REDIRECT
    # ---------------------------------------------------------

    print("[EDVANTO REGISTER] SUCCESS")
    print(
        "[EDVANTO REGISTER] Redirecting to: "
        "/verify-otp/"
    )
    print("=" * 70 + "\n")

    messages.success(
        request,
        "A verification code has been sent to your email."
    )


    return redirect("core:verify_otp")


# ============================================================
# OTP VERIFICATION
# ============================================================

# ============================================================
# OTP VERIFICATION
# ============================================================

def verify_otp_view(request):

    # --------------------------------------------------------
    # Get pending registration
    # --------------------------------------------------------

    pending_registration = request.session.get(
        "pending_registration"
    )

    pending_created_at = request.session.get(
        "pending_registration_created_at"
    )

    if not pending_registration or not pending_created_at:

        messages.error(
            request,
            "Your registration session has expired. "
            "Please register again."
        )

        return redirect("core:sign_in")

    # --------------------------------------------------------
    # Check registration session expiry
    # --------------------------------------------------------

    try:

        created_at = datetime.fromisoformat(
            pending_created_at
        )

    except (ValueError, TypeError):

        request.session.pop(
            "pending_registration",
            None,
        )

        request.session.pop(
            "pending_registration_created_at",
            None,
        )

        messages.error(
            request,
            "Your registration session is invalid. "
            "Please register again."
        )

        return redirect("core:sign_in")

    if timezone.is_naive(created_at):
        created_at = timezone.make_aware(created_at)

    if timezone.now() > created_at + timedelta(
        minutes=OTP_EXPIRY_MINUTES
    ):

        request.session.pop(
            "pending_registration",
            None,
        )

        request.session.pop(
            "pending_registration_created_at",
            None,
        )

        messages.error(
            request,
            "Your verification session has expired. "
            "Please register again."
        )

        return redirect("core:sign_in")

    # --------------------------------------------------------
    # Display OTP page
    # --------------------------------------------------------

    if request.method == "GET":

        return render(
            request,
            "verify-otp.html",
            {
                "email": pending_registration["email"],
            },
        )

    # --------------------------------------------------------
    # OTP submission
    # --------------------------------------------------------

    if request.method != "POST":
        return redirect("core:verify_otp")

    submitted_otp = request.POST.get(
        "otp",
        ""
    ).strip()

    if not submitted_otp:

        messages.error(
            request,
            "Please enter the verification code."
        )

        return render(
            request,
            "verify-otp.html",
            {
                "email": pending_registration["email"],
            },
        )

    # --------------------------------------------------------
    # Get latest registration OTP
    # --------------------------------------------------------

    otp_record = (
        OTPVerification.objects
        .filter(
            email=pending_registration["email"],
            purpose=OTPVerification.Purpose.REGISTRATION,
            is_verified=False,
        )
        .order_by("-created_at")
        .first()
    )

    if not otp_record:

        messages.error(
            request,
            "No active verification code was found. "
            "Please register again."
        )

        return redirect("core:sign_in")

    # --------------------------------------------------------
    # Verify OTP
    # --------------------------------------------------------

    valid, error_message = verify_otp(
        otp_record,
        submitted_otp,
    )

    if not valid:

        messages.error(
            request,
            error_message,
        )

        return render(
            request,
            "verify-otp.html",
            {
                "email": pending_registration["email"],
            },
        )

    # --------------------------------------------------------
    # Create student account
    # --------------------------------------------------------

    try:

        user = create_student_from_registration(
            email=pending_registration["email"],
            full_name=pending_registration["full_name"],
            phone=pending_registration["phone"],
            password_hash=pending_registration["password_hash"],
        )

    except (ValueError, IntegrityError):

        request.session.pop(
            "pending_registration",
            None,
        )

        request.session.pop(
            "pending_registration_created_at",
            None,
        )

        messages.error(
            request,
            "We could not create your account. "
            "The email may already be registered."
        )

        return redirect("core:sign_in")

    # --------------------------------------------------------
    # Clear pending registration
    # --------------------------------------------------------

    request.session.pop(
        "pending_registration",
        None,
    )

    request.session.pop(
        "pending_registration_created_at",
        None,
    )

    request.session.modified = True

    # ---------------------------------------------------------
    # CREATE REGISTRATION NOTIFICATIONS FOR ADMIN USERS
    # ---------------------------------------------------------
    try:
        User = get_user_model()
        
        # Fetch all admin / staff users so they receive the notification in their panel
        admin_users = User.objects.filter(is_staff=True)

        for admin in admin_users:
            # Create the Notification record for the admin
            notification = Notification.objects.create(
                recipient=admin,
                title="New Student Registration",
                message=f"Student {pending_registration['full_name']} ({pending_registration['email']}) has successfully verified their account.",
                notification_type=Notification.NotificationType.SYSTEM,
                is_read=False,
            )

            # Create the Notification Delivery record (In-App)
            NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationDelivery.Channel.IN_APP,
                status=NotificationDelivery.Status.SENT,
                sent_at=timezone.now(),
            )
            
        print("[EDVANTO REGISTER] Admin notifications created successfully")
    except Exception as exc:
        print(f"[EDVANTO REGISTER] Warning: Failed to create admin notifications: {exc}")

    # --------------------------------------------------------
    # Registration completed
    # --------------------------------------------------------

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    messages.success(
        request,
        "Welcome to Edvanto! Your account has been verified successfully.",
        extra_tags="Registration Successful!",
    )

    return redirect("core:dashboard")

# ============================================================
# LOGIN
# ============================================================

def login_view(request):

    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "GET":
        return render(
            request,
            "login.html",
            {"next": next_url},
        )

    if request.method != "POST":
        return redirect("core:login")

    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")

    if not email:
        messages.error(request, "Email address is required.")
        return render(
            request,
            "login.html",
            {
                "next": next_url,
                "login_errors": {"email": "Email address is required."},
                "login_data": {"email": email},
            },
            status=400,
        )

    if not password:
        messages.error(request, "Password is required.")
        return render(
            request,
            "login.html",
            {
                "next": next_url,
                "login_errors": {"password": "Password is required."},
                "login_data": {"email": email},
            },
            status=400,
        )

    user = authenticate(
        request,
        username=email,
        password=password,
    )

    if user is None:
        messages.error(request, "Invalid email or password.")
        return render(
            request,
            "login.html",
            {
                "next": next_url,
                "login_errors": {
                    "password": "Invalid email or password."
                },
                "login_data": {"email": email},
            },
            status=401,
        )

    if not user.is_active:
        messages.error(request, "Your account is inactive. Please contact support.")
        return render(
            request,
            "login.html",
            {
                "next": next_url,
                "login_errors": {
                    "email": "Your account is inactive."
                },
                "login_data": {"email": email},
            },
            status=403,
        )

    # The current admin_panel.permissions policy is intentionally
    # superuser-only. Do not silently grant admin-panel access to a user
    # merely because their custom role field says "admin".
    if user.role == User.Role.ADMIN and not user.is_superuser:
        messages.error(
            request,
            "This admin account is not authorized for the admin panel. Contact the system administrator."
        )
        return render(
            request,
            "login.html",
            {
                "next": next_url,
                "login_errors": {
                    "email": (
                        "This admin account is not authorized for the admin panel. "
                        "Contact the system administrator."
                    )
                },
                "login_data": {"email": email},
            },
            status=403,
        )

    login(request, user)

    # Route according to role with appropriate confirmation messages
    if user.is_superuser:
        messages.success(
            request,
            "Welcome to the Edvanto administration panel.",
            extra_tags="Admin Access Granted",
        )
        return redirect("admin_panel:dashboard")

    if user.role == User.Role.CENTER or (hasattr(user, "managed_center") and user.managed_center):
        center = getattr(user, "managed_center", None)
        if not center:
            center = Center.objects.filter(owner=user).first()

        if center:
            if center.is_suspended:
                logout(request)
                messages.error(request, "Your center account has been suspended. Please contact Edvanto support.")
                return redirect("core:login")
            if center.has_active_subscription:
                messages.success(request, f"Welcome to {center.name} Center Panel.", extra_tags="Welcome Back!")
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    return redirect(next_url)
                return redirect("center_panel:dashboard")
            else:
                messages.warning(request, "Please choose a subscription plan to activate your Center Dashboard.")
                return redirect("core:center_subscription_select")
        else:
            app = CenterApplication.objects.filter(user=user).first() or CenterApplication.objects.filter(owner_email=user.email).first()
            if app and app.status in [CenterApplication.Status.PENDING, CenterApplication.Status.UNDER_REVIEW]:
                logout(request)
                messages.info(request, "Your center application is currently under review by our administrator.")
                return redirect("core:login")

    if user.role == User.Role.INSTRUCTOR:
        messages.success(request, "Welcome to the Edvanto Instructor Panel.", extra_tags="Welcome Back!")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect("instructor_panel:dashboard")

    if user.role == User.Role.STUDENT:
        messages.success(
            request,
            "You have successfully logged in to Edvanto.",
            extra_tags="Welcome Back!",
        )
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
        ):
            return redirect(next_url)
        return redirect("core:dashboard")

    messages.success(
        request,
        "You have successfully logged in to Edvanto.",
        extra_tags="Welcome Back!",
    )
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
    ):
        return redirect(next_url)

    return redirect("core:dashboard")



def logout_view(request):
    logout(request)
    messages.success(
        request,
        "You have been logged out successfully. See you again!",
        extra_tags="Logged Out Successfully",
    )
    return redirect("core:home")


def sign_in(request):
    return render(request, "sign-in.html")


def forgot_password(request):
    """
    Initiates password reset by verifying email and sending a secure one-time reset link.
    """
    if request.method == "GET":
        return render(request, "forgot-password.html")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        if not email:
            return render(
                request,
                "forgot-password.html",
                {"error": "Please enter your email address.", "email": email},
                status=400,
            )

        # Look up user by email or username
        user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()

        # Send reset email if user exists and is active
        if user and user.is_active:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(
                reverse("core:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
            )

            # Generate OTP code for extra verification convenience
            otp = None
            try:
                _, otp = create_otp(
                    email=user.email or email,
                    purpose=OTPVerification.Purpose.PASSWORD_RESET,
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
            except Exception:
                pass

            user_display_name = user.get_full_name() or user.username
            subject = "Reset your Edvanto password"
            message_body = (
                f"Hello {user_display_name},\n\n"
                f"We received a request to reset the password for your Edvanto account.\n\n"
                f"Click the link below to set a new password:\n"
                f"{reset_url}\n\n"
            )
            if otp:
                message_body += f"Your password reset verification code is: {otp}\n\n"

            message_body += (
                "This link expires in 30 minutes.\n\n"
                "If you did not request a password reset, you can safely ignore this email.\n\n"
                "Regards,\n"
                "Edvanto Team"
            )

            try:
                send_mail(
                    subject=subject,
                    message=message_body,
                    from_email=None,
                    recipient_list=[user.email or email],
                    fail_silently=False,
                )
                print(f"[EDVANTO PASSWORD RESET] Sent reset link to {user.email or email}: {reset_url}")
            except Exception as exc:
                print(f"[EDVANTO PASSWORD RESET] Email sending error: {exc}")

        return render(
            request,
            "forgot-password.html",
            {
                "success": True,
                "sent_email": email,
            },
        )


def password_reset_confirm(request, uidb64, token):
    """
    Validates the password reset token and allows user to specify a new password.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    # Check token validity
    if user is None or not default_token_generator.check_token(user, token):
        return render(
            request,
            "reset-password.html",
            {
                "validlink": False,
                "error": "This password reset link is invalid or has expired. Please request a new link.",
            },
        )

    if request.method == "GET":
        return render(
            request,
            "reset-password.html",
            {
                "validlink": True,
                "uidb64": uidb64,
                "token": token,
                "user_name": user.get_full_name() or user.username,
            },
        )

    if request.method == "POST":
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        if not new_password or not confirm_password:
            return render(
                request,
                "reset-password.html",
                {
                    "validlink": True,
                    "uidb64": uidb64,
                    "token": token,
                    "user_name": user.get_full_name() or user.username,
                    "error": "Both password fields are required.",
                },
                status=400,
            )

        if len(new_password) < 8:
            return render(
                request,
                "reset-password.html",
                {
                    "validlink": True,
                    "uidb64": uidb64,
                    "token": token,
                    "user_name": user.get_full_name() or user.username,
                    "error": "Password must be at least 8 characters long.",
                },
                status=400,
            )

        if new_password != confirm_password:
            return render(
                request,
                "reset-password.html",
                {
                    "validlink": True,
                    "uidb64": uidb64,
                    "token": token,
                    "user_name": user.get_full_name() or user.username,
                    "error": "Passwords do not match.",
                },
                status=400,
            )

        # Set new password and save
        user.set_password(new_password)
        user.save()

        messages.success(
            request,
            "Your password has been reset successfully! You can now log in with your new password.",
        )
        return redirect("core:login")

@login_required
def course_detail(request, slug):
    course = get_object_or_404(
        Course.objects
        .select_related(
            "instructor",
            "center",
        ),
        slug=slug,
        status=Course.Status.PUBLISHED,
    )

    related_courses = (
        Course.objects
        .filter(
            status=Course.Status.PUBLISHED,
            category=course.category,
        )
        .exclude(pk=course.pk)
        .order_by("-created_at")[:3]
    )

    enrollment = None
    other_enrolled_course = None

    if request.user.is_authenticated:
        enrollment = (
            Enrollment.objects
            .filter(
                student=request.user,
                course=course,
            )
            .first()
        )
        if request.user.role == User.Role.STUDENT:
            other_enr = get_student_active_or_pending_enrollment(request.user, exclude_course=course)
            if other_enr:
                other_enrolled_course = other_enr.course

    return render(
        request,
        "course_details.html",
        {
            "course": course,
            "related_courses": related_courses,
            "enrollment": enrollment,
            "other_enrolled_course": other_enrolled_course,
        },
    )




# ============================================================
# PAYMENT
# ============================================================

@login_required
@require_POST
def test_payment(request, slug):

    if request.user.role != User.Role.STUDENT:
        messages.error(
            request,
            "Only students can purchase courses.",
        )
        return redirect("core:courses")

    course = get_object_or_404(
        Course.objects.filter(
            status=Course.Status.PUBLISHED
        ),
        slug=slug,
    )

    other_enr = get_student_active_or_pending_enrollment(request.user, exclude_course=course)
    if other_enr:
        messages.error(
            request,
            f"You are already enrolled in '{other_enr.course.title}'. "
            "Edvanto permits enrollment in only one course at a time.",
        )
        return redirect("core:dashboard")

    try:
        order, payment_transaction, enrollment = (
            create_test_payment(
                student=request.user,
                course=course,
            )
        )

    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "core:course_detail",
            slug=course.slug,
        )

    if (
        enrollment.approval_status
        == Enrollment.ApprovalStatus.ACCEPTED
    ):
        messages.success(
            request,
            "Test payment successful. "
            "Your course access is now active.",
        )
        return redirect("core:dashboard")

    messages.warning(
        request,
        "Payment recorded successfully. Your enrollment is awaiting approval. "
        "Course access will remain locked until approval.",
    )

    return redirect(
        "core:course_detail",
        slug=course.slug,
    )


@login_required
@require_POST
def offline_payment_request(request, slug):
    return payment(request, slug)


@login_required
def payment(request, slug):
    User = get_user_model()

    if request.user.role != User.Role.STUDENT:
        messages.error(
            request,
            "Only students can enroll in courses."
        )
        return redirect("core:courses")

    course = get_object_or_404(
        Course.objects.filter(
            status=Course.Status.PUBLISHED
        ),
        slug=slug,
    )

    # Restriction: Student cannot enroll in another course if already enrolled in one
    other_enr = get_student_active_or_pending_enrollment(request.user, exclude_course=course)
    if other_enr:
        messages.warning(
            request,
            f"You are already enrolled in '{other_enr.course.title}'. "
            "Edvanto permits enrollment in only one course at a time. Please complete your current course first.",
        )
        return redirect("core:dashboard")

    enrollment = (
        Enrollment.objects
        .filter(
            student=request.user,
            course=course,
        )
        .first()
    )

    if enrollment is not None:
        if enrollment.payment_status == Enrollment.PaymentStatus.PAID:
            messages.info(
                request,
                "You are already enrolled in this course."
            )
            return redirect("core:course_dashboard", slug=course.slug)
        elif enrollment.approval_status == Enrollment.ApprovalStatus.PENDING and request.method == "GET":
            messages.warning(
                request,
                "Your enrollment for this course is pending administrative approval."
            )
            return redirect("core:dashboard")

    if request.method == "POST":
        user = request.user
        full_name = (
            request.POST.get("full_name", "").strip()
            or request.POST.get("name", "").strip()
            or user.get_full_name()
            or user.username
        )
        email = request.POST.get("email", "").strip() or user.email
        phone = request.POST.get("phone", "").strip() or user.phone
        address = request.POST.get("address", "").strip() or getattr(user, "bio", "")
        notes = request.POST.get("notes", "").strip()

        # Update student user profile details if provided
        update_fields = []
        if full_name:
            parts = full_name.split(" ", 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
            update_fields.extend(["first_name", "last_name"])
        if phone:
            user.phone = phone
            update_fields.append("phone")
        if address:
            user.bio = address
            update_fields.append("bio")
        if update_fields:
            user.save(update_fields=list(set(update_fields)))

        # Create or update offline enrollment request
        try:
            order, txn, enr = create_offline_payment_request(
                student=user,
                course=course,
                payment_mode=request.POST.get("payment_mode", "Direct Offline"),
                transaction_reference=request.POST.get("transaction_reference", "DIRECT-OFFLINE"),
                notes=notes,
            )
            if txn:
                txn.metadata.update({
                    "direct_enrollment": True,
                    "student_name": full_name,
                    "student_email": email,
                    "student_phone": phone,
                    "student_address": address,
                    "notes": notes,
                })
                txn.save(update_fields=["metadata"])
        except ValueError as exc:
            # If already pending, update metadata on existing order/txn
            existing_order = (
                Order.objects
                .filter(student=user, course=course, payment_method=Order.PaymentMethod.OFFLINE)
                .exclude(status=Order.Status.PAID)
                .order_by("-created_at")
                .first()
            )
            if existing_order:
                txn = existing_order.transactions.order_by("-created_at").first()
                if txn:
                    txn.metadata.update({
                        "direct_enrollment": True,
                        "student_name": full_name,
                        "student_email": email,
                        "student_phone": phone,
                        "student_address": address,
                        "notes": notes,
                    })
                    txn.save(update_fields=["metadata"])
            if enrollment:
                enrollment.approval_status = Enrollment.ApprovalStatus.PENDING
                enrollment.payment_status = Enrollment.PaymentStatus.PENDING
                enrollment.save(update_fields=["approval_status", "payment_status"])

        # Notify admin users
        admin_users = User.objects.filter(is_staff=True)
        for admin in admin_users:
            create_admin_notification(
                recipient=admin,
                title="New Offline Payment Request",
                message=f"{full_name} submitted an offline payment for '{course.title}'",
                n_type=Notification.NotificationType.PAYMENT,
            )

        messages.warning(
            request,
            f"Your offline payment request for '{course.title}' has been submitted and is pending administrative approval."
        )
        return redirect("core:dashboard")

    # GET request: Calculate effective price
    price = course.discounted_price if (course.discounted_price and course.discounted_price > 0) else course.price

    return render(
        request,
        "payment.html",
        {
            "course": course,
            "price": price,
            "today_date": timezone.now().strftime("%Y-%m-%d"),
        },
    )


@login_required
@require_POST
def razorpay_verify(request, slug):
    if request.user.role != User.Role.STUDENT:
        messages.error(
            request,
            "Only students can purchase courses."
        )
        return redirect("core:courses")

    course = get_object_or_404(
        Course.objects.filter(
            status=Course.Status.PUBLISHED
        ),
        slug=slug,
    )

    other_enr = get_student_active_or_pending_enrollment(request.user, exclude_course=course)
    if other_enr:
        messages.error(
            request,
            f"You are already enrolled in '{other_enr.course.title}'. "
            "Multiple course enrollments are restricted.",
        )
        return redirect("core:dashboard")

    razorpay_order_id = request.POST.get("razorpay_order_id", "").strip()
    razorpay_payment_id = request.POST.get("razorpay_payment_id", "").strip()
    razorpay_signature = request.POST.get("razorpay_signature", "").strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        messages.error(
            request,
            "Incomplete payment verification payload received. Please try again."
        )
        return redirect("core:payment", slug=course.slug)

    try:
        order, payment_transaction, enrollment = verify_and_complete_razorpay_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            student=request.user,
        )
    except ValueError as exc:
        messages.error(
            request,
            str(exc)
        )
        return redirect("core:payment", slug=course.slug)

    if enrollment.approval_status == Enrollment.ApprovalStatus.ACCEPTED:
        messages.success(
            request,
            f"Payment successful! You are now enrolled in '{course.title}'. Enjoy learning!"
        )
        return redirect("core:course_dashboard", slug=course.slug)

    messages.success(
        request,
        f"Payment received! Your enrollment for '{course.title}' is awaiting instructor approval."
    )
    return redirect("core:dashboard")


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    from django.http import HttpResponse, HttpResponseBadRequest
    webhook_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    webhook_signature = request.headers.get("X-Razorpay-Signature", "")

    client = get_razorpay_client()
    if webhook_secret and client:
        try:
            client.utility.verify_webhook_signature(
                request.body.decode("utf-8"),
                webhook_signature,
                webhook_secret,
            )
        except Exception:
            return HttpResponseBadRequest("Invalid webhook signature")

    try:
        event_payload = json.loads(request.body.decode("utf-8"))
        event_type = event_payload.get("event")
        payload_data = event_payload.get("payload", {})

        if event_type in ("payment.captured", "order.paid"):
            payment_entity = payload_data.get("payment", {}).get("entity", {})
            order_entity = payload_data.get("order", {}).get("entity", {})

            razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id")
            razorpay_payment_id = payment_entity.get("id")

            if razorpay_order_id and razorpay_payment_id:
                try:
                    verify_and_complete_razorpay_payment(
                        razorpay_order_id=razorpay_order_id,
                        razorpay_payment_id=razorpay_payment_id,
                        razorpay_signature="",
                        is_webhook=True,
                    )
                except Exception:
                    pass

        return HttpResponse(status=200)
    except Exception:
        return HttpResponseBadRequest("Invalid webhook payload")


@login_required
def dashboard(request):

    user = request.user

    if user.role != User.Role.STUDENT:
        messages.error(
            request,
            "The student dashboard is available only to student accounts.",
        )
        return redirect("core:home")

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related(
            "course",
            "course__instructor",
            "course__center",
        )
        .order_by("-enrolled_at")
    )

    # INITIALIZE THESE VARIABLES EXPLICITLY HERE:
    active_enrollment = None
    current_lesson = None
    learning_progress = []

    for enrollment in enrollments:

        if not enrollment_has_access(enrollment):
            continue

        active_enrollment = enrollment

        if enrollment.course.mode == Course.Mode.ONLINE:

            current_lesson = get_current_unlocked_lesson(
                enrollment
            )

            learning_progress = list(
                enrollment.lesson_progress
                .select_related(
                    "lesson",
                    "lesson__module",
                )
                .order_by(
                    "lesson__module__unlock_order",
                    "lesson__module__order",
                    "lesson__unlock_order",
                    "lesson__order",
                    "lesson__pk",
                )
            )

        break

    pending_enrollment = next(
        (e for e in enrollments if e.approval_status == Enrollment.ApprovalStatus.PENDING),
        None,
    )
    rejected_enrollment = next(
        (e for e in enrollments if e.approval_status == Enrollment.ApprovalStatus.REJECTED),
        None,
    )
    

    # DEDICATED OFFLINE STUDENT DASHBOARD
    if active_enrollment and active_enrollment.course.mode == Course.Mode.OFFLINE:
        center = active_enrollment.course.center
        batch = (
            Batch.objects
            .filter(course=active_enrollment.course)
            .select_related("instructor", "center")
            .first()
        )
        sessions = []
        if batch:
            sessions = list(
                batch.sessions
                .select_related("instructor")
                .order_by("date", "start_time")
            )

        attendance_records = list(
            Attendance.objects
            .filter(student=user, session__batch__course=active_enrollment.course)
            .select_related("session", "marked_by")
            .order_by("-session__date", "-session__start_time")
        )
        total_sessions_held = len(attendance_records)
        present_count = sum(1 for a in attendance_records if a.status == Attendance.Status.PRESENT)
        absent_count = sum(1 for a in attendance_records if a.status == Attendance.Status.ABSENT)
        late_count = sum(1 for a in attendance_records if a.status == Attendance.Status.LATE)
        excused_count = sum(1 for a in attendance_records if a.status == Attendance.Status.EXCUSED)
        attendance_rate = int((present_count / total_sessions_held * 100)) if total_sessions_held > 0 else 100

        modules = list(
            active_enrollment.course.modules
            .prefetch_related("lessons", "lessons__materials", "lessons__resources")
            .order_by("order")
        )

        assessments = list(
            Assessment.objects
            .filter(module__course=active_enrollment.course, is_published=True)
            .select_related("module")
            .order_by("module__order", "unlock_order")
        )

        doubt_threads = list(
            DoubtThread.objects
            .filter(student=user, enrollment=active_enrollment)
            .order_by("-updated_at")[:5]
        )

        return render(
            request,
            "dashboard/student/offline_dashboard.html",
            {
                "enrollments": enrollments,
                "active_enrollment": active_enrollment,
                "course": active_enrollment.course,
                "center": center,
                "batch": batch,
                "sessions": sessions,
                "attendance_records": attendance_records,
                "total_sessions_held": total_sessions_held,
                "present_count": present_count,
                "absent_count": absent_count,
                "late_count": late_count,
                "excused_count": excused_count,
                "attendance_rate": attendance_rate,
                "modules": modules,
                "assessments": assessments,
                "doubt_threads": doubt_threads,
                "dash_section": "dashboard",
                "is_student": True,
                "is_offline_student": True,
                "student_name": user.get_full_name() or user.username,
                "student_initials": (
                    (user.first_name[:1] if user.first_name else "") +
                    (user.last_name[:1] if user.last_name else "")
                ).upper() or "S",
                "dashboard_welcome": True,
            },
        )

    return render(
        request,
        "dashboard/student/dashboard.html",
        {
            "enrollments": enrollments,
            "active_enrollment": active_enrollment,
            "pending_enrollment": pending_enrollment,
            "rejected_enrollment": rejected_enrollment,
            "current_lesson": current_lesson,
            "learning_progress": learning_progress,
            "dash_section": "dashboard",
            "is_student": True,
            "student_name": user.get_full_name() or user.username,
            "student_initials": (
                (user.first_name[:1] if user.first_name else "") +
                (user.last_name[:1] if user.last_name else "")
            ).upper() or "S",
            "dashboard_welcome": True,
        },
    )

@login_required
def lesson_view(request, lesson_id):

    if request.user.role != User.Role.STUDENT:
        messages.error(request, "Only students can access lessons.")
        return redirect("core:dashboard")

    lesson = get_object_or_404(
        Lesson.objects.select_related("module", "module__course"),
        pk=lesson_id,
    )

    course = lesson.module.course
    enrollment = get_student_enrollment(request.user, course)

    if enrollment is None:
        messages.error(request, "You are not enrolled in this course.")
        return redirect("core:dashboard")

    if not enrollment_has_access(enrollment):
        messages.warning(request, "You do not currently have access to this course.")
        return redirect("core:dashboard")

    if not lesson_is_accessible(enrollment, lesson):
        messages.warning(request, "This lesson is currently locked.")
        return redirect("core:dashboard")

    record_lesson_opened(enrollment, lesson)
    progress = get_learning_progress(enrollment, lesson)

    # Study material, video, resources
    materials_list = list(lesson.materials.filter(is_active=True).order_by("title", "pk"))
    for m in materials_list:
        fname = (m.original_filename or m.title or "").lower()
        m.is_doc = m.material_type in ("docx", "text", "doc") or fname.endswith((".docx", ".txt", ".md", ".doc"))
        m.is_pdf = m.material_type == "pdf" or fname.endswith(".pdf")
        m.is_image = m.material_type == "image" or fname.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
        if m.is_doc:
            try:
                m.file.open("rb")
                blob = m.file.read()
                m.file.close()
                m.note_html = convert_material_to_note_html(decrypt_bytes(blob), m.original_filename or m.title, m.material_type)
            except Exception:
                m.note_html = "<p class='text-muted'><em>Study note preview is currently unavailable.</em></p>"
        else:
            m.note_html = None
    materials = materials_list
    video_asset = getattr(lesson, "video_asset", None)
    video_state = get_lesson_video_state(lesson)
    resources = lesson.resources.order_by("title", "pk")

    # All published lessons of this course, in curriculum order
    all_lessons = list(
        Lesson.objects
        .filter(Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True), module__course=course)
        .select_related("module")
        .order_by(
            "module__unlock_order", "module__order",
            "unlock_order", "order", "pk",
        )
    )

    # Build ONE list of rows — lesson + its progress — no dict needed
    progress_by_lesson_id = {
        row.lesson_id: row
        for row in enrollment.lesson_progress.all()
    }
    sidebar_rows = [
        {
            "lesson": l,
            "progress": progress_by_lesson_id.get(l.pk),
        }
        for l in all_lessons
    ]

    # Next lesson (the one right after the current lesson in that list)
    next_lesson = None
    for i, l in enumerate(all_lessons):
        if l.pk == lesson.pk and i + 1 < len(all_lessons):
            next_lesson = all_lessons[i + 1]
            break

    return render(
        request,
        "dashboard/student/lesson.html",
        {
            "lesson": lesson,
            "course": course,
            "module": lesson.module,

            # base_dashboard.html expects `active_enrollment`
            "active_enrollment": enrollment,
            # ...and uses `enrollment` in the lesson body — keep both
            "enrollment": enrollment,

            "progress": progress,
            "next_lesson": next_lesson,

            "materials": materials,
            "video_asset": video_asset,
            "video_state": video_state,
            "resources": resources,
            "sidebar_rows": sidebar_rows,

            # Doubts & Assessments for this lesson:
            "lesson_doubts": DoubtThread.objects.filter(student=request.user, lesson=lesson).prefetch_related("messages").order_by("-created_at"),
            "lesson_assessments": [
                (setattr(a, "passed", assessment_is_passed(a, request.user)) or a)
                for a in Assessment.objects.filter(lesson=lesson, is_published=True).order_by("unlock_order", "pk")
            ],
            "module_assessments": [
                (setattr(a, "passed", assessment_is_passed(a, request.user)) or a)
                for a in Assessment.objects.filter(module=lesson.module, is_published=True).order_by("unlock_order", "pk")
            ],
            # Sidebar / header bits the base template reads:
            "current_lesson": lesson,
            "dash_section": "lesson",
            "student_name": (
                request.user.get_full_name() or request.user.username
            ),
            "student_initials": (
                (request.user.first_name[:1] if request.user.first_name else "")
                + (request.user.last_name[:1] if request.user.last_name else "")
            ).upper() or "S",
        },
    )



# ============================================================
# LESSON PROGRESS API
# ============================================================

@login_required
@require_POST
def lesson_progress_api(request, lesson_id):

    if request.user.role != User.Role.STUDENT:
        return JsonResponse(
            {
                "success": False,
                "error": "Student access required.",
            },
            status=403,
        )

    lesson = get_object_or_404(
        Lesson.objects.select_related(
            "module",
            "module__course",
        ),
        pk=lesson_id,
    )

    enrollment = get_student_enrollment(
        request.user,
        lesson.module.course,
    )

    if enrollment is None:
        return JsonResponse(
            {
                "success": False,
                "error": "Enrollment not found.",
            },
            status=403,
        )

    try:
        watched_percent = request.POST.get(
            "watched_percent",
            "0",
        )

        position_seconds = request.POST.get(
            "position_seconds",
            "0",
        )

        duration_seconds = request.POST.get(
            "duration_seconds",
            None,
        )

        progress = update_video_progress(
            enrollment=enrollment,
            lesson=lesson,
            watched_percent=watched_percent,
            position_seconds=position_seconds,
            duration_seconds=duration_seconds,
        )

    except PermissionError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=403,
        )

    except ValueError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "watched_percent": float(
                progress.watched_percent
            ),
            "position_seconds": (
                progress.last_position_seconds
            ),
            "status": progress.status,
        }
    )


# ============================================================
# LESSON COMPLETION API
# ============================================================

@login_required
@require_POST
def lesson_complete_api(request, lesson_id):

    if request.user.role != User.Role.STUDENT:
        return JsonResponse(
            {
                "success": False,
                "error": "Student access required.",
            },
            status=403,
        )

    lesson = get_object_or_404(
        Lesson.objects.select_related(
            "module",
            "module__course",
        ),
        pk=lesson_id,
    )

    enrollment = get_student_enrollment(
        request.user,
        lesson.module.course,
    )

    if enrollment is None:
        return JsonResponse(
            {
                "success": False,
                "error": "Enrollment not found.",
            },
            status=403,
        )

    try:
        progress, next_lesson = complete_lesson(
            enrollment=enrollment,
            lesson=lesson,
        )

    except PermissionError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=403,
        )

    except ValueError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "lesson_completed": True,
            "progress_percent": float(
                enrollment.progress_percent
            ),
            "next_lesson_id": (
                next_lesson.id
                if next_lesson
                else None
            ),
            "course_completed": (
                next_lesson is None
            ),
        }
    )

@login_required
def course_dashboard(request, slug):
    """
    Two responsibilities, same URL:

    1) If the student is enrolled in the requested course AND has access,
       render the dedicated My Course learning workspace.

    2) Otherwise, fall back to the existing enrollments list page
       (dashboard/student/my_courses.html) — preserving old behaviour.
    """
    if request.user.role != User.Role.STUDENT:
        messages.error(
            request,
            "Only students can access their courses."
        )
        return redirect("core:dashboard")

    enrollments = list(
        Enrollment.objects
        .filter(student=request.user)
        .select_related(
            "course",
            "course__instructor",
            "course__center",
        )
        .order_by("-enrolled_at")
    )

    # Try to resolve the slug against the student's own enrollments only.
    active_enrollment = next(
        (e for e in enrollments if e.course.slug == slug),
        None,
    )

    # If the slug is not the student's, fall back to the list view.
    if active_enrollment is None:
        messages.warning(
            request,
            "You are not enrolled in that course.",
        )
        return render(
            request,
            "dashboard/student/my_courses.html",
            {"enrollments": enrollments},
        )

    # If the student is enrolled but access is currently denied
    # (pending approval, unpaid, paused), send them to the course
    # detail page so they can see/resolve the reason — same pattern
    # the dashboard view already uses.
    if not enrollment_has_access(active_enrollment):
        if active_enrollment.approval_status == Enrollment.ApprovalStatus.PENDING:
            messages.warning(
                request,
                f"Your enrollment for "
                f"“{active_enrollment.course.title}” is awaiting approval.",
            )
        elif active_enrollment.access_paused:
            messages.warning(
                request,
                f"Your access to "
                f"“{active_enrollment.course.title}” is currently paused.",
            )
        else:
            messages.warning(
                request,
                f"You do not currently have access to "
                f"“{active_enrollment.course.title}”.",
            )
        return redirect(
            "core:course_detail",
            slug=active_enrollment.course.slug,
        )

    # -------- Build the My Course workspace context --------
    course = active_enrollment.course

    current_lesson = None
    learning_progress = []

    if course.mode == Course.Mode.ONLINE:
        # Populate initial progress records for all published lessons if not yet created
        initialize_learning_progress(active_enrollment)
        current_lesson = get_current_unlocked_lesson(active_enrollment)

        # Same queryset the dashboard view uses — ordered exactly the
        # way the curriculum expects.
        learning_progress = list(
            active_enrollment.lesson_progress
            .select_related(
                "lesson",
                "lesson__module",
            )
            .order_by(
                "lesson__module__unlock_order",
                "lesson__module__order",
                "lesson__unlock_order",
                "lesson__order",
                "lesson__pk",
            )
        )

    # Fast lookup: lesson_id -> progress row.
    # Template uses this to render per-lesson status without N+1.
    progress_by_lesson = {
        row.lesson_id: row for row in learning_progress
    }

    # Query published modules with lessons and attach per-lesson progress
    modules_list = list(
        course.modules.all().order_by("order", "pk")
    )
    for m in modules_list:
        m_lessons = list(
            m.lessons.filter(Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True))
            .order_by("unlock_order", "order", "pk")
        )
        for l in m_lessons:
            l.progress = progress_by_lesson.get(l.pk)
        m.published_lessons = m_lessons

    return render(
        request,
        "dashboard/student/my_course.html",
        {
            # shared shell context (same shape as dashboard)
            "enrollments": enrollments,
            "active_enrollment": active_enrollment,
            "current_lesson": current_lesson,
            "learning_progress": learning_progress,
            "progress_by_lesson": progress_by_lesson,
            "modules": modules_list,
            "dash_section": "course_curriculum",
            "is_student": True,
            "student_name": (
                request.user.get_full_name()
                or request.user.username
            ),
            "student_initials": (
                (request.user.first_name[:1] if request.user.first_name else "")
                + (request.user.last_name[:1] if request.user.last_name else "")
            ).upper() or "S",
            # My Course uses these too (may be None — template guards them)
            "materials_summary": None,
            "assessment_status": None,
            "pending_assessments": 0,
            "open_doubts": 0,
            "unread_notifications": 0,
            "notifications": [],
        },
    )

# ============================================================
# CAREER CONSULTATION REQUEST
# ============================================================

@require_POST
def career_consultation_request(request):
    """
    Allow only registered student accounts to submit career consultation requests.
    """
    if not request.user.is_authenticated or getattr(request.user, "role", None) != User.Role.STUDENT:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({
                "status": "error",
                "message": "Career consultation is only available to registered students. Please sign in or create an account."
            }, status=403)
        messages.error(request, "Career consultation is an exclusive feature for registered students. Please sign in or register.")
        return redirect("core:sign_in")

    form = CareerConsultationForm(request.POST)
    if not form.is_valid():
        first_error = next(iter(form.errors.values()))[0] if form.errors else "Please fill in all required fields properly."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": first_error}, status=400)
        messages.error(request, first_error)
        return redirect(request.META.get("HTTP_REFERER", "core:home"))

    preferred_date = form.cleaned_data.get("preferred_date")
    phone = form.cleaned_data.get("phone")
    message = form.cleaned_data.get("message")

    student_name = request.user.get_full_name() or request.user.username
    student_email = request.user.email

    booking = ConsultationBooking.objects.create(
        name=student_name,
        email=student_email,
        phone=phone,
        preferred_date=preferred_date,
        message=message,
        status=ConsultationBooking.Status.NEW,
    )

    # Notify all admins and staff members in-app 
    admin_users = User.objects.filter(is_staff=True)
    for admin_user in admin_users:
        Notification.objects.create(
            recipient=admin_user,
            title="Career Consultation Request",
            message=f"{student_name} submitted career consultation request.",
            notification_type = Notification.NotificationType.SYSTEM,
            is_read=False
        )

    success_msg = f"Thank you, {student_name}! Your career consultation request has been registered (Ref #{booking.pk}). Our mentorship team will contact you shortly."
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "status": "success",
            "message": success_msg,
            "booking_id": booking.pk,
        })

    messages.success(request, success_msg)
    return redirect(request.META.get("HTTP_REFERER", "core:home"))


# ============================================================
# STUDENT DOUBT CLEARANCE
# ============================================================

@login_required
def student_doubts(request):
    """List all doubts asked by the logged-in student."""
    user = request.user
    if user.role != User.Role.STUDENT:
        messages.error(request, "This area is only for students.")
        return redirect("core:home")

    threads = (
        DoubtThread.objects
        .filter(student=user)
        .select_related("lesson", "lesson__module", "lesson__module__course", "assigned_instructor")
        .prefetch_related("messages")
        .order_by("-updated_at")
    )

    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        threads = threads.filter(status=status_filter)

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related("course")
        .order_by("-enrolled_at")
    )
    active_enrollment = next((e for e in enrollments if enrollment_has_access(e)), None)
    current_lesson = get_current_unlocked_lesson(active_enrollment) if active_enrollment else None

    context = {
        "threads": threads,
        "selected_status": status_filter,
        "enrollments": enrollments,
        "active_enrollment": active_enrollment,
        "current_lesson": current_lesson,
        "dash_section": "doubts",
        "is_student": True,
        "student_name": user.get_full_name() or user.username,
        "student_initials": (
            (user.first_name[:1] if user.first_name else "") +
            (user.last_name[:1] if user.last_name else "")
        ).upper() or "S",
        "open_doubts": DoubtThread.objects.filter(
            student=user,
            status__in=[DoubtThread.Status.OPEN, DoubtThread.Status.ANSWERED, DoubtThread.Status.REOPENED]
        ).count(),
    }
    return render(request, "dashboard/student/doubts.html", context)


@login_required
@require_POST
def create_doubt(request, lesson_id):
    """Submit a new doubt thread for a specific lesson."""
    user = request.user
    if user.role != User.Role.STUDENT:
        return JsonResponse({"status": "error", "message": "Only students can ask doubts."}, status=403)

    lesson = get_object_or_404(
        Lesson.objects.select_related("module", "module__course"),
        pk=lesson_id
    )

    enrollment = Enrollment.objects.filter(
        student=user,
        course=lesson.module.course
    ).first()
    if not enrollment or not enrollment_has_access(enrollment):
        messages.error(request, "You must be actively enrolled in this course to ask doubts.")
        return redirect("core:student_doubts")

    subject = request.POST.get("subject", "").strip()
    message_text = request.POST.get("message", "").strip()
    attachment = request.FILES.get("attachment")

    if not subject or not message_text:
        messages.error(request, "Please provide both a subject and details for your doubt.")
        return redirect("core:lesson", lesson_id=lesson.pk)

    course = lesson.module.course
    assigned_instructor = None
    if course.instructor and course.instructor.is_active and course.instructor.role == User.Role.INSTRUCTOR:
        assigned_instructor = course.instructor

    thread = DoubtThread.objects.create(
        student=user,
        enrollment=enrollment,
        lesson=lesson,
        subject=subject,
        status=DoubtThread.Status.OPEN,
        assigned_instructor=assigned_instructor,
    )
    DoubtMessage.objects.create(
        thread=thread,
        sender=user,
        message=message_text,
        attachment=attachment,
    )

    if assigned_instructor:
        notif = Notification.objects.create(
            recipient=assigned_instructor,
            title="New Student Doubt Assigned",
            message=f"Student {user.get_full_name() or user.username} asked a doubt on '{lesson.title}' ({course.title}).",
            notification_type=Notification.NotificationType.DOUBT,
            is_read=False,
        )
        NotificationDelivery.objects.create(
            notification=notif,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.SENT,
            sent_at=timezone.now(),
        )
    else:
        recipients = list(User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(role=User.Role.ADMIN)))
        if course.center and course.center.owner and course.center.owner.is_active:
            recipients.append(course.center.owner)
        for recipient in set(recipients):
            notif = Notification.objects.create(
                recipient=recipient,
                title="Unassigned Student Doubt",
                message=f"Student {user.get_full_name() or user.username} asked a doubt on '{course.title}' which requires an instructor assignment.",
                notification_type=Notification.NotificationType.DOUBT,
                is_read=False,
            )
            NotificationDelivery.objects.create(
                notification=notif,
                channel=NotificationDelivery.Channel.IN_APP,
                status=NotificationDelivery.Status.SENT,
                sent_at=timezone.now(),
            )
 


    messages.success(request, f"Your doubt regarding '{lesson.title}' has been submitted. Our instructor will reply soon!")
    return redirect("core:doubt_detail", thread_id=thread.pk)


@login_required
def doubt_detail(request, thread_id):
    """View doubt conversation timeline for student."""
    user = request.user
    thread = get_object_or_404(
        DoubtThread.objects.select_related(
            "student", "lesson", "lesson__module", "lesson__module__course", "assigned_instructor"
        ),
        pk=thread_id,
        student=user
    )
    messages_list = thread.messages.select_related("sender").order_by("created_at")

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related("course")
        .order_by("-enrolled_at")
    )
    active_enrollment = next((e for e in enrollments if enrollment_has_access(e)), None)
    current_lesson = get_current_unlocked_lesson(active_enrollment) if active_enrollment else None

    context = {
        "thread": thread,
        "messages_list": messages_list,
        "enrollments": enrollments,
        "active_enrollment": active_enrollment,
        "current_lesson": current_lesson,
        "dash_section": "doubts",
        "is_student": True,
        "student_name": user.get_full_name() or user.username,
        "student_initials": (
            (user.first_name[:1] if user.first_name else "") +
            (user.last_name[:1] if user.last_name else "")
        ).upper() or "S",
    }
    return render(request, "dashboard/student/doubt_detail.html", context)


@login_required
@require_POST
def doubt_reply(request, thread_id):
    """Post student follow-up message to doubt thread."""
    user = request.user
    thread = get_object_or_404(DoubtThread, pk=thread_id, student=user)
    message_text = request.POST.get("message", "").strip()
    attachment = request.FILES.get("attachment")

    if message_text or attachment:
        DoubtMessage.objects.create(
            thread=thread,
            sender=user,
            message=message_text,
            attachment=attachment,
        )
        if thread.status in [DoubtThread.Status.RESOLVED, DoubtThread.Status.ANSWERED, DoubtThread.Status.CLOSED]:
            thread.status = DoubtThread.Status.REOPENED
        else:
            thread.status = DoubtThread.Status.OPEN
        thread.save()

        if thread.assigned_instructor:
            notif = Notification.objects.create(
                recipient=thread.assigned_instructor,
                title="Student Follow-up on Doubt",
                message=f"Student {user.get_full_name() or user.username} posted a follow-up on '{thread.subject}'.",
                notification_type=Notification.NotificationType.DOUBT,
                is_read=False,
            )
            NotificationDelivery.objects.create(
                notification=notif,
                channel=NotificationDelivery.Channel.IN_APP,
                status=NotificationDelivery.Status.SENT,
                sent_at=timezone.now(),
            )

        messages.success(request, "Follow-up message sent.")

    return redirect("core:doubt_detail", thread_id=thread.pk)


@login_required
@require_POST
def doubt_resolve(request, thread_id):
    """Student marks doubt as resolved."""
    user = request.user
    thread = get_object_or_404(DoubtThread, pk=thread_id, student=user)
    thread.status = DoubtThread.Status.RESOLVED
    thread.save()
    messages.success(request, "Thread marked as resolved! Feel free to ask whenever you need help.")
    return redirect("core:doubt_detail", thread_id=thread.pk)


# ============================================================
# STUDENT ASSESSMENTS
# ============================================================

@login_required
def student_assessments(request):
    """List all available assessments for enrolled courses."""
    user = request.user
    if user.role != User.Role.STUDENT:
        messages.error(request, "This area is only for students.")
        return redirect("core:home")

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related("course")
        .order_by("-enrolled_at")
    )
    active_enrollment = next((e for e in enrollments if enrollment_has_access(e)), None)

    enrolled_courses = [e.course for e in enrollments if enrollment_has_access(e)]
    assessments = (
        Assessment.objects
        .filter(module__course__in=enrolled_courses, is_published=True)
        .select_related("module", "module__course")
        .order_by("module__course__title", "module__order", "unlock_order", "pk")
    )

    current_lesson = get_current_unlocked_lesson(active_enrollment) if active_enrollment else None

    assessments_list = []
    for a in assessments:
        subs = list(
            Submission.objects
            .filter(assessment=a, student=user)
            .order_by("-score", "-submitted_at")
        )
        a.attempts_taken = len(subs)
        a.best_submission = subs[0] if subs else None
        a.passed = assessment_is_passed(a, user)
        assessments_list.append(a)

    context = {
        "assessments": assessments_list,
        "enrollments": enrollments,
        "active_enrollment": active_enrollment,
        "current_lesson": current_lesson,
        "dash_section": "assessment",
        "is_student": True,
        "student_name": user.get_full_name() or user.username,
        "student_initials": (
            (user.first_name[:1] if user.first_name else "") +
            (user.last_name[:1] if user.last_name else "")
        ).upper() or "S",
    }
    return render(request, "dashboard/student/assessments.html", context)


@login_required
def take_assessment(request, assessment_id):
    """Take or submit an assessment."""
    user = request.user
    assessment = get_object_or_404(
        Assessment.objects.select_related("module", "module__course"),
        pk=assessment_id,
        is_published=True
    )

    enrollment = Enrollment.objects.filter(
        student=user,
        course=assessment.module.course
    ).first()
    if not enrollment or not enrollment_has_access(enrollment):
        messages.error(request, "You must be enrolled in this course to take this assessment.")
        return redirect("core:student_assessments")

    subs_count = Submission.objects.filter(assessment=assessment, student=user).count()
    if assessment.attempts_allowed > 0 and subs_count >= assessment.attempts_allowed:
        messages.warning(request, f"You have reached the maximum allowed attempts ({assessment.attempts_allowed}) for this assessment.")
        last_sub = Submission.objects.filter(assessment=assessment, student=user).order_by("-submitted_at").first()
        if last_sub:
            return redirect("core:assessment_result", submission_id=last_sub.pk)
        return redirect("core:student_assessments")

    questions = list(assessment.questions.all().order_by("order", "pk"))

    if request.method == "POST":
        answers = {}
        total_mcq_obtained = Decimal("0")
        has_manual_questions = False
        uploaded_file = request.FILES.get("submission_file")

        for q in questions:
            field_name = f"question_{q.pk}"
            if q.question_type == Question.QuestionType.MCQ:
                ans = request.POST.get(field_name, "").strip()
                answers[str(q.pk)] = ans
                if q.check_answer(ans):
                    total_mcq_obtained += Decimal(str(q.marks))
            elif q.question_type == Question.QuestionType.TEXT:
                has_manual_questions = True
                ans = request.POST.get(field_name, "").strip()
                answers[str(q.pk)] = ans
            elif q.question_type == Question.QuestionType.FILE:
                has_manual_questions = True
                f = request.FILES.get(field_name)
                if f:
                    uploaded_file = f
                    answers[str(q.pk)] = f.name

        if not has_manual_questions:
            final_score = total_mcq_obtained
            status = Submission.Status.GRADED
        else:
            final_score = total_mcq_obtained
            status = Submission.Status.SUBMITTED

        submission = Submission.objects.create(
            assessment=assessment,
            student=user,
            answers=answers,
            uploaded_file=uploaded_file,
            score=final_score,
            status=status,
            graded_at=timezone.now() if status == Submission.Status.GRADED else None,
        )

        LearningEvent.objects.create(
            student=user,
            enrollment=enrollment,
            event_type=LearningEvent.EventType.ASSESSMENT_COMPLETED,
            progress=final_score,
        )

        total_possible = assessment.total_marks or sum(q.marks for q in questions) or 1
        percentage = (final_score / Decimal(str(total_possible))) * Decimal("100")
        if percentage >= Decimal(str(assessment.pass_percentage)):
            update_enrollment_progress(enrollment)

        messages.success(request, f"Assessment '{assessment.title}' submitted successfully!")
        return redirect("core:assessment_result", submission_id=submission.pk)

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related("course")
        .order_by("-enrolled_at")
    )
    active_enrollment = next((e for e in enrollments if enrollment_has_access(e)), None)
    current_lesson = get_current_unlocked_lesson(active_enrollment) if active_enrollment else None

    context = {
        "assessment": assessment,
        "questions": questions,
        "attempts_left": max(0, assessment.attempts_allowed - subs_count) if assessment.attempts_allowed > 0 else "Unlimited",
        "enrollments": enrollments,
        "active_enrollment": active_enrollment,
        "current_lesson": current_lesson,
        "dash_section": "assessment",
        "is_student": True,
        "student_name": user.get_full_name() or user.username,
        "student_initials": (
            (user.first_name[:1] if user.first_name else "") +
            (user.last_name[:1] if user.last_name else "")
        ).upper() or "S",
    }
    return render(request, "dashboard/student/take_assessment.html", context)


@login_required
def assessment_result(request, submission_id):
    """View result and breakdown of an assessment submission."""
    user = request.user
    submission = get_object_or_404(
        Submission.objects.select_related(
            "assessment", "assessment__module", "assessment__module__course", "student"
        ),
        pk=submission_id,
        student=user
    )
    course = submission.assessment.module.course
    enrollment = Enrollment.objects.filter(
        student=user,
        course=course,
    ).first()
    if not enrollment or not enrollment_has_access(enrollment):
        messages.error(request, "You do not currently have access to this assessment result.")
        return redirect("core:student_assessments")
    assessment = submission.assessment
    questions = list(assessment.questions.all().order_by("order", "pk"))

    total_marks = assessment.total_marks or sum(q.marks for q in questions) or 1
    score = submission.score or Decimal("0")
    percentage = (score / Decimal(str(total_marks))) * Decimal("100") if total_marks > 0 else Decimal("0")
    passed = percentage >= assessment.pass_percentage

    reviewed_questions = []
    for q in questions:
        student_ans = submission.answers.get(str(q.pk), "")
        is_correct = (q.question_type == Question.QuestionType.MCQ and q.check_answer(student_ans))
        reviewed_questions.append({
            "question": q,
            "student_answer": student_ans,
            "is_correct": is_correct,
            "marks_awarded": q.marks if is_correct else 0,
            "correct_display": q.get_correct_answer_display(),
        })

    enrollments = list(
        Enrollment.objects
        .filter(student=user)
        .select_related("course")
        .order_by("-enrolled_at")
    )
    active_enrollment = next((e for e in enrollments if enrollment_has_access(e)), None)
    current_lesson = get_current_unlocked_lesson(active_enrollment) if active_enrollment else None

    context = {
        "submission": submission,
        "assessment": assessment,
        "score": score,
        "total_marks": total_marks,
        "percentage": round(percentage, 1),
        "passed": passed,
        "reviewed_questions": reviewed_questions,
        "enrollments": enrollments,
        "active_enrollment": active_enrollment,
        "current_lesson": current_lesson,
        "dash_section": "assessment",
        "is_student": True,
        "student_name": user.get_full_name() or user.username,
        "student_initials": (
            (user.first_name[:1] if user.first_name else "") +
            (user.last_name[:1] if user.last_name else "")
        ).upper() or "S",
    }
    return render(request, "dashboard/student/assessment_result.html", context)



@login_required
def notification(request):
    """Render notification list for the logged-in user."""
    notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")
    return render(
        request,
        "notifications/list.html",
        {"notifications": notifications},
    )


# ============================================================
# CENTER REGISTRATION & SUBSCRIPTION VIEWS
# ============================================================

def join_as_center(request):
    """
    Public registration page for training centers to partner with Edvanto.
    """
    from core.center_services import (
        validate_center_application_data,
        send_center_registration_otp,
        create_center_application,
    )

    if request.method == "GET":
        return render(
            request,
            "join_as_center.html",
            {"form_data": {}, "form_errors": {}},
        )

    if request.method != "POST":
        return redirect("core:join_as_center")

    validation = validate_center_application_data(request.POST, request.FILES)

    if not validation["is_valid"]:
        return render(
            request,
            "join_as_center.html",
            {
                "form_data": request.POST,
                "form_errors": validation["errors"],
            },
            status=400,
        )

    cleaned = validation["cleaned_data"]

    # Create the CenterApplication in PENDING status
    app = create_center_application(
        cleaned,
        files=request.FILES,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )

    # Generate and send OTP to owner email
    try:
        otp_record, otp = send_center_registration_otp(
            owner_email=cleaned["owner_email"],
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except Exception as exc:
        messages.error(request, f"Could not send verification OTP: {exc}")
        return render(
            request,
            "join_as_center.html",
            {"form_data": request.POST, "form_errors": {"general": str(exc)}},
            status=400,
        )

    request.session["pending_center_application_id"] = app.id
    request.session["pending_center_owner_email"] = cleaned["owner_email"]

    messages.success(request, f"A 6-digit verification code has been sent to {cleaned['owner_email']}.")
    return redirect("core:center_verify_otp")


def center_verify_otp(request):
    """
    Verify OTP for center application submission.
    """
    app_id = request.session.get("pending_center_application_id")
    owner_email = request.session.get("pending_center_owner_email")

    if not app_id or not owner_email:
        messages.error(request, "No pending center registration found. Please submit the form.")
        return redirect("core:join_as_center")

    application = get_object_or_404(CenterApplication, pk=app_id)

    if request.method == "GET":
        return render(
            request,
            "center_verify_otp.html",
            {"email": owner_email, "error": None},
        )

    if request.method != "POST":
        return redirect("core:center_verify_otp")

    submitted_otp = request.POST.get("otp", "").strip()

    otp_record = (
        OTPVerification.objects
        .filter(
            email=owner_email,
            purpose=OTPVerification.Purpose.CENTER_REGISTRATION,
            is_verified=False,
        )
        .order_by("-created_at")
        .first()
    )

    if not otp_record:
        return render(
            request,
            "center_verify_otp.html",
            {"email": owner_email, "error": "No pending OTP found. Please request a new code."},
            status=400,
        )

    success, error_msg = verify_otp(otp_record, submitted_otp)

    if not success:
        return render(
            request,
            "center_verify_otp.html",
            {"email": owner_email, "error": error_msg or "Invalid OTP code."},
            status=400,
        )

    # Verification successful
    request.session.pop("pending_center_application_id", None)
    request.session.pop("pending_center_owner_email", None)

    messages.success(request, "Your application has been verified and submitted for administrative review.")
    return redirect("core:center_registration_success", application_id=application.id)


def center_registration_success(request, application_id):
    """
    Confirmation screen showing application reference number and status.
    """
    application = get_object_or_404(CenterApplication, pk=application_id)
    return render(
        request,
        "center_registration_success.html",
        {"application": application},
    )


@login_required
def center_subscription_select(request):
    """
    Allow an approved center owner to view and choose a subscription plan.
    """
    from core.center_services import ensure_default_subscription_plans
    ensure_default_subscription_plans()

    center = getattr(request.user, "managed_center", None)
    if not center:
        center = Center.objects.filter(owner=request.user).first()

    if not center and not request.user.is_superuser:
        messages.error(request, "You do not have an approved center associated with your account.")
        return redirect("core:home")

    plans = CenterSubscriptionPlan.objects.filter(is_active=True).order_by("duration_months")

    return render(
        request,
        "center_subscription_select.html",
        {
            "center": center,
            "plans": plans,
        },
    )


@login_required
def center_subscription_checkout(request, plan_id):
    """
    Initialize payment for the selected subscription plan.
    """
    from core.center_services import create_center_subscription_order

    center = getattr(request.user, "managed_center", None)
    if not center:
        center = Center.objects.filter(owner=request.user).first()

    if not center and not request.user.is_superuser:
        messages.error(request, "You do not have an approved center associated with your account.")
        return redirect("core:home")

    plan = get_object_or_404(CenterSubscriptionPlan, pk=plan_id, is_active=True)

    try:
        subscription, payment, gateway_configured = create_center_subscription_order(center=center, plan=plan)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("core:center_subscription_select")

    context = {
        "center": center,
        "plan": plan,
        "subscription": subscription,
        "payment": payment,
        "gateway_configured": gateway_configured,
        "razorpay_order_id": payment.razorpay_order_id,
        "razorpay_key_id": getattr(settings, "RAZORPAY_KEY_ID", ""),
        "amount_in_paise": int(plan.price * 100),
    }

    return render(request, "center_subscription_checkout.html", context)


@login_required
@require_POST
def center_subscription_verify(request):
    """
    Verify payment signature and activate subscription.
    """
    from core.center_services import verify_center_subscription_payment

    razorpay_order_id = request.POST.get("razorpay_order_id", "").strip()
    razorpay_payment_id = request.POST.get("razorpay_payment_id", "").strip()
    razorpay_signature = request.POST.get("razorpay_signature", "").strip()

    if not razorpay_order_id or not razorpay_payment_id:
        messages.error(request, "Missing payment verification parameters.")
        return redirect("core:center_subscription_select")

    try:
        subscription, payment = verify_center_subscription_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )
        messages.success(
            request,
            f"Payment successful! Your {subscription.plan.name} has been activated until {subscription.end_date:%d %B %Y}.",
        )
        return redirect("center_panel:dashboard")
    except ValueError as exc:
        messages.error(request, f"Payment verification error: {exc}")
        return redirect("core:center_subscription_select")


@csrf_exempt
def center_subscription_webhook(request):
    """
    Handle asynchronous webhook notifications from Razorpay for center subscriptions.
    Idempotent.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    webhook_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    webhook_signature = request.headers.get("X-Razorpay-Signature", "")
    payload_body = request.body

    client = get_razorpay_client()
    if client and webhook_secret and webhook_signature:
        try:
            client.utility.verify_webhook_signature(
                payload_body.decode("utf-8"),
                webhook_signature,
                webhook_secret,
            )
        except Exception as exc:
            return JsonResponse({"detail": f"Invalid webhook signature: {exc}"}, status=400)

    try:
        data = json.loads(payload_body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    event = data.get("event")
    if event in ("payment.captured", "order.paid"):
        payment_entity = data.get("payload", {}).get("payment", {}).get("entity", {})
        rp_order_id = payment_entity.get("order_id")
        rp_payment_id = payment_entity.get("id")

        if rp_order_id:
            from core.center_services import verify_center_subscription_payment
            try:
                verify_center_subscription_payment(
                    razorpay_order_id=rp_order_id,
                    razorpay_payment_id=rp_payment_id,
                    razorpay_signature="",
                    is_webhook=True,
                )
            except Exception as exc:
                logger.error(f"Error processing subscription webhook: {exc}")

    return JsonResponse({"status": "ok"})

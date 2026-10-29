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


User = get_user_model()


# ============================================================
# PUBLIC PAGES
# ============================================================

# views.py

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

    # --------------------------------------------------------
    # Registration completed
    # --------------------------------------------------------

    messages.success(
        request,
        "Your account has been created successfully. "
        "You can now log in."
    )

    return redirect("core:login")


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

    # Send authorized administrators directly to the protected admin panel.
    # Student enrollment-aware routing below remains unchanged.
    if user.is_superuser:
        return redirect("admin_panel:dashboard")

    if user.role == User.Role.STUDENT:

        active_enrollment = (
            Enrollment.objects
            .select_related("course")
            .filter(
                student=user,
                approval_status=Enrollment.ApprovalStatus.ACCEPTED,
                payment_status__in=[
                    Enrollment.PaymentStatus.PAID,
                    Enrollment.PaymentStatus.PARTIALLY_PAID,
                ],
                access_paused=False,
            )
            .order_by("-enrolled_at")
            .first()
        )

        if active_enrollment is not None:
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
            ):
                return redirect(next_url)
            return redirect("core:dashboard")

        pending_enrollment = (
            Enrollment.objects
            .select_related("course")
            .filter(
                student=user,
                approval_status=Enrollment.ApprovalStatus.PENDING,
            )
            .order_by("-enrolled_at")
            .first()
        )

        if pending_enrollment:
            messages.warning(
                request,
                f"Your enrollment for "
                f"“{pending_enrollment.course.title}” is awaiting approval.",
            )
            return redirect(
                "core:course_detail",
                slug=pending_enrollment.course.slug,
            )

        return redirect("core:courses")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
    ):
        return redirect(next_url)

    return redirect("core:dashboard")



@require_POST
def logout_view(request):
    logout(request)
    messages.success(
        request,
        "You have been logged out successfully.",
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
    if request.user.role != User.Role.STUDENT:
        messages.error(
            request,
            "Only students can request course enrollment.",
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

    payment_mode = request.POST.get("payment_mode", "UPI").strip()
    transaction_reference = request.POST.get("transaction_reference", "").strip()
    payment_date = request.POST.get("payment_date", "").strip()
    notes = request.POST.get("notes", "").strip()

    try:
        order, payment_transaction, enrollment = create_offline_payment_request(
            student=request.user,
            course=course,
            payment_mode=payment_mode,
            transaction_reference=transaction_reference,
            payment_date=payment_date or None,
            notes=notes,
        )
    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "core:payment",
            slug=course.slug,
        )

    ref_str = f" (Ref: {transaction_reference})" if transaction_reference else ""
    messages.success(
        request,
        f"Your offline payment request for '{course.title}'{ref_str} has been submitted! "
        "Our team will verify your transaction details and activate course access shortly.",
    )
    return redirect("core:dashboard")


@login_required
def payment(request, slug):
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
        elif enrollment.approval_status == Enrollment.ApprovalStatus.PENDING:
            messages.warning(
                request,
                "Your enrollment for this course is pending administrative approval."
            )
            return redirect("core:dashboard")

    # Calculate effective price
    price = course.discounted_price if (course.discounted_price and course.discounted_price > 0) else course.price
    price_paise = int(price * 100) if price else 0

    razorpay_key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    razorpay_order_id = ""
    razorpay_available = False

    if razorpay_key_id and getattr(settings, "RAZORPAY_KEY_SECRET", ""):
        try:
            _, _, rp_order = create_razorpay_order(student=request.user, course=course)
            razorpay_order_id = rp_order.get("id", "")
            razorpay_available = True
        except Exception as exc:
            # If Razorpay client failed (e.g. invalid test keys or offline dev), keep graceful
            razorpay_available = False

    return render(
        request,
        "payment.html",
        {
            "course": course,
            "price": price,
            "price_paise": price_paise,
            "razorpay_available": razorpay_available,
            "razorpay_key_id": razorpay_key_id,
            "razorpay_order_id": razorpay_order_id,
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

    # Never render the dashboard for a student who has no accepted,
    # paid/partially-paid and unpaused enrollment.
    if active_enrollment is None:

        pending_enrollment = next(
            (
                enrollment
                for enrollment in enrollments
                if enrollment.approval_status
                == Enrollment.ApprovalStatus.PENDING
            ),
            None,
        )

        if pending_enrollment is not None:
            messages.warning(
                request,
                f"Your enrollment for "
                f"“{pending_enrollment.course.title}” "
                f"is awaiting approval.",
            )
            return redirect(
                "core:course_detail",
                slug=pending_enrollment.course.slug,
            )

        rejected_enrollment = next(
            (
                enrollment
                for enrollment in enrollments
                if enrollment.approval_status
                == Enrollment.ApprovalStatus.REJECTED
            ),
            None,
        )

        if rejected_enrollment is not None:
            messages.error(
                request,
                f"Your enrollment for "
                f"“{rejected_enrollment.course.title}” "
                f"is not currently approved.",
            )
            return redirect(
                "core:course_detail",
                slug=rejected_enrollment.course.slug,
            )
        

        # ADDED MESSAGE:
        messages.warning(request, "Please select a course to access your student dashboard.")
        return redirect("core:courses")
    

    # DEDICATED OFFLINE STUDENT DASHBOARD
    if active_enrollment.course.mode == Course.Mode.OFFLINE:
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
        return redirect("core:courses")

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
            "resources": resources,
            "sidebar_rows": sidebar_rows,

            # Doubts & Assessments for this lesson:
            "lesson_doubts": DoubtThread.objects.filter(student=request.user, lesson=lesson).prefetch_related("messages").order_by("-created_at"),
            "module_assessments": Assessment.objects.filter(module=lesson.module, is_published=True).order_by("unlock_order"),
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

        progress = update_video_progress(
            enrollment=enrollment,
            lesson=lesson,
            watched_percent=watched_percent,
            position_seconds=position_seconds,
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
        return redirect("core:lesson", lesson_id=lesson.pk)

    subject = request.POST.get("subject", "").strip()
    message_text = request.POST.get("message", "").strip()
    attachment = request.FILES.get("attachment")

    if not subject or not message_text:
        messages.error(request, "Please provide both a subject and details for your doubt.")
        return redirect("core:lesson", lesson_id=lesson.pk)

    thread = DoubtThread.objects.create(
        student=user,
        enrollment=enrollment,
        lesson=lesson,
        subject=subject,
        status=DoubtThread.Status.OPEN,
    )
    DoubtMessage.objects.create(
        thread=thread,
        sender=user,
        message=message_text,
        attachment=attachment,
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
        return redirect("core:courses")

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
                if ans and ans == q.correct_answer:
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
    assessment = submission.assessment
    questions = list(assessment.questions.all().order_by("order", "pk"))

    total_marks = assessment.total_marks or sum(q.marks for q in questions) or 1
    score = submission.score or Decimal("0")
    percentage = (score / Decimal(str(total_marks))) * Decimal("100") if total_marks > 0 else Decimal("0")
    passed = percentage >= assessment.pass_percentage

    reviewed_questions = []
    for q in questions:
        student_ans = submission.answers.get(str(q.pk), "")
        is_correct = (q.question_type == Question.QuestionType.MCQ and student_ans == q.correct_answer)
        reviewed_questions.append({
            "question": q,
            "student_answer": student_ans,
            "is_correct": is_correct,
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

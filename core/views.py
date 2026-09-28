from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.core.mail import send_mail
from django.db import IntegrityError
from django.utils import timezone
from datetime import datetime, timedelta 

from .auth_services import (
    OTP_EXPIRY_MINUTES,
    create_otp,
    normalize_email, 
    verify_otp,
    create_student_from_registration,
)

from .models import *

from .registration_services import (
    validate_student_registration,
)


User = get_user_model()


# ============================================================
# PUBLIC PAGES
# ============================================================

def home(request):
    return render(request, "home.html")


def courses(request):
    return render(request, "courses.html")


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
        return render(request, "sign-in.html")

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

        messages.error(
            request,
            "Please accept the terms and privacy policy."
        )

        return redirect("core:sign_in")

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

        for error in result["errors"]:
            print(f"  ERROR: {error}")
            messages.error(request, error)

        return redirect("core:sign_in")

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

    if request.method == "GET":
        return render(request, "login.html")

    if request.method != "POST":
        return redirect("core:login")

    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")

    if not email:
        messages.error(request, "Email address is required.")
        return redirect("core:login")

    if not password:
        messages.error(request, "Password is required.")
        return redirect("core:login")

    user = authenticate(
        request,
        username=email,
        password=password,
    )

    if user is None:
        messages.error(
            request,
            "Invalid email or password."
        )
        return redirect("core:login")

    if not user.is_active:
        messages.error(
            request,
            "Your account is inactive."
        )
        return redirect("core:login")

    login(request, user)

    # ---------------------------------------------------------
    # STUDENT ACCESS CHECK
    # ---------------------------------------------------------

    if user.role == User.Role.STUDENT:

        enrollment = (
            Enrollment.objects
            .select_related("course")
            .filter(student=user)
            .order_by("-enrolled_at")
            .first()
        )

        # No course enrollment
        if enrollment is None:
            return redirect("core:courses")

        # Enrollment rejected
        if enrollment.approval_status == "rejected":
            messages.warning(
                request,
                "Your enrollment has not been approved."
            )
            return redirect("core:courses")

        # Enrollment waiting for approval
        if enrollment.approval_status == "pending":
            messages.info(
                request,
                "Your enrollment is waiting for approval."
            )
            return redirect("core:courses")

        # Enrollment accepted
        if enrollment.approval_status == "accepted":

            if enrollment.course.mode == "online":
                return redirect("core:dashboard")

            if enrollment.course.mode == "offline":
                return redirect("core:dashboard")

        # Safety fallback
        messages.error(
            request,
            "We could not determine your course access."
        )
        return redirect("core:courses")

    # ---------------------------------------------------------
    # NON-STUDENT USERS
    # ---------------------------------------------------------

    return redirect("core:dashboard")


def sign_in(request):
    return render(request, "sign-in.html")


def forgot_password(request):
    return render(request, "forgot-password.html")


def course_detail(request):
    return render(request, "course_details.html")


def dashboard(request):
    return render(request, "dashboard/student/dashboard.html")
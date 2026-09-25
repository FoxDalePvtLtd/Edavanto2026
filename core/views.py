from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import get_user_model
from .auth_services import (
    OTP_MAX_ATTEMPTS,
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

    # --------------------------------------------------------
    # Display registration page
    # --------------------------------------------------------

    if request.method == "GET":
        return render(request, "sign-in.html")


    # --------------------------------------------------------
    # Only POST requests continue below
    # --------------------------------------------------------

    if request.method != "POST":
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Honeypot protection
    # --------------------------------------------------------
    # This field should be hidden in the registration form.
    # Normal users should never fill it.

    honeypot = request.POST.get("website", "").strip()

    if honeypot:
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Get registration data
    # --------------------------------------------------------

    full_name = request.POST.get("full_name", "").strip()
    email = request.POST.get("email", "").strip().lower()
    phone = request.POST.get("phone", "").strip()
    password = request.POST.get("password", "")
    confirm_password = request.POST.get("confirm_password", "")


    # --------------------------------------------------------
    # Required field validation
    # --------------------------------------------------------

    if not full_name:
        messages.error(request, "Full name is required.")
        return redirect("core:sign_in")

    if not email:
        messages.error(request, "Email address is required.")
        return redirect("core:sign_in")

    if not phone:
        messages.error(request, "Phone number is required.")
        return redirect("core:sign_in")

    if not password:
        messages.error(request, "Password is required.")
        return redirect("core:sign_in")

    if not confirm_password:
        messages.error(request, "Please confirm your password.")
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Password confirmation
    # --------------------------------------------------------

    if password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Check existing email
    # --------------------------------------------------------

    if User.objects.filter(email__iexact=email).exists():
        messages.error(
            request,
            "An account with this email already exists."
        )
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Generate username
    # --------------------------------------------------------
    # The current User model still uses Django's username field.
    # We use the email as the username because registration is
    # email-based.

    username = email


    # --------------------------------------------------------
    # Check username
    # --------------------------------------------------------

    if User.objects.filter(username=username).exists():
        messages.error(
            request,
            "An account with this email already exists."
        )
        return redirect("core:sign_in")


    # --------------------------------------------------------
    # Store pending registration data
    # --------------------------------------------------------
    #
    # IMPORTANT:
    # We are NOT creating the User yet.
    #
    # The account will be created only after successful OTP
    # verification.
    #
    # Password is stored temporarily in the session only for
    # this pending registration flow. We will replace this
    # with the proper secure OTP/verification architecture
    # before production.

    request.session["pending_registration"] = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "username": username,
        "password": password,
    }


    # --------------------------------------------------------
    # Next step: OTP verification
    # --------------------------------------------------------

    messages.success(
        request,
        "Registration details accepted. OTP verification is required."
    )

    return redirect("core:sign_in")


# ============================================================
# LOGIN
# ============================================================

def login_view(request):
    return render(request, "login.html")


def sign_in(request):
    return render(request, "sign-in.html")


def forgot_password(request):
    return render(request, "forgot-password.html")

def course_detail(request):
    return render(request, "course_details.html")

def dashboard(request):
    return render(request, "dashboard/student/dashboard.html")
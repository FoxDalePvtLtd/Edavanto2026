from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model, authenticate, login, logout
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
    return render(request, "forgot-password.html")

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

    if request.user.is_authenticated:
        enrollment = (
            Enrollment.objects
            .filter(
                student=request.user,
                course=course,
            )
            .first()
        )

    return render(
        request,
        "course_details.html",
        {
            "course": course,
            "related_courses": related_courses,
            "enrollment": enrollment,
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

    try:
        order, payment_transaction, enrollment = (
            create_offline_payment_request(
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

    messages.warning(
        request,
        "Offline payment request submitted. "
        "Course access will remain locked until admin approval.",
    )

    return redirect(
        "core:course_detail",
        slug=course.slug,
    )


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

    enrollment = (
        Enrollment.objects
        .filter(
            student=request.user,
            course=course,
        )
        .first()
    )

    if enrollment is not None:
        messages.info(
            request,
            "You already have an enrollment for this course."
        )
        return redirect("core:dashboard")

    return render(
        request,
        "payment.html",
        {
            "course": course,
        },
    )
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
    

    return render(
        request,
        "dashboard/student/dashboard.html",
        {
            "enrollments": enrollments,
            "active_enrollment": active_enrollment,
            "current_lesson": current_lesson,
            "learning_progress": learning_progress,
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
        messages.error(
            request,
            "Only students can access lessons."
        )
        return redirect("core:dashboard")

    lesson = get_object_or_404(
        Lesson.objects
        .select_related(
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
        messages.error(
            request,
            "You are not enrolled in this course."
        )
        return redirect("core:courses")

    if not enrollment_has_access(enrollment):
        messages.warning(
            request,
            "You do not currently have access to this course."
        )
        return redirect("core:dashboard")

    if not lesson_is_accessible(
        enrollment,
        lesson,
    ):
        messages.warning(
            request,
            "This lesson is currently locked."
        )
        return redirect("core:dashboard")

    record_lesson_opened(
        enrollment,
        lesson,
    )

    progress = get_learning_progress(
        enrollment,
        lesson,
    )

    next_lesson = None

    return render(
        request,
        "dashboard/student/lesson.html",
        {
            "lesson": lesson,
            "enrollment": enrollment,
            "progress": progress,
            "next_lesson": next_lesson,
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
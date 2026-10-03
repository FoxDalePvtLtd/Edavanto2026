from django.shortcuts import render

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden

from django.db.models import Q, Sum
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone

from core.models import (
    User, Course, Enrollment, Order, Installment, Batch, BatchSession,
    Assessment, Submission, DoubtThread, ConsultationBooking, Certificate,
)
from .forms import *
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .permissions import admin_required


@admin_required
@require_GET
def dashboard(request):
    """Render the protected dashboard using real, aggregate-backed data."""
    today = timezone.localdate()
    students_count = User.objects.filter(role=User.Role.STUDENT).count()
    course_count = Course.objects.count()
    published_course_count = Course.objects.filter(status=Course.Status.PUBLISHED).count()
    pending_enrollments_count = Enrollment.objects.filter(
        approval_status=Enrollment.ApprovalStatus.PENDING
    ).count()
    paid_revenue = Order.objects.filter(status=Order.Status.PAID).aggregate(
        total=Sum("total_amount")
    )["total"] or 0
    pending_installments_count = Installment.objects.filter(
        status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE]
    ).count()

    recent_enrollments = Enrollment.objects.select_related(
        "student", "course"
    ).order_by("-enrolled_at")[:6]

    context = {
        "page_title": "Dashboard",
        "students_count": students_count,
        "course_count": course_count,
        "published_course_count": published_course_count,
        "pending_enrollments_count": pending_enrollments_count,
        "paid_revenue": paid_revenue,
        "pending_installments_count": pending_installments_count,
        "enrollment_count": Enrollment.objects.count(),
        "active_batches_count": Batch.objects.filter(status=Batch.Status.ACTIVE).count(),
        "upcoming_sessions_count": BatchSession.objects.filter(
            date__gte=today, status=BatchSession.Status.SCHEDULED
        ).count(),
        "assessment_count": Assessment.objects.count(),
        "submission_count": Submission.objects.count(),
        "open_doubts_count": DoubtThread.objects.filter(
            status__in=[DoubtThread.Status.OPEN, DoubtThread.Status.ASSIGNED,
                        DoubtThread.Status.IN_PROGRESS, DoubtThread.Status.REOPENED]
        ).count(),
        "consultation_count": ConsultationBooking.objects.count(),
        "certificate_count": Certificate.objects.filter(
            status=Certificate.Status.ISSUED
        ).count(),
        "recent_enrollments": recent_enrollments,
    }
    return render(request, "dashboard.html", context)


# ==================================================
# USERS
# ==================================================

@admin_required
@require_GET
def user_list(request):
    """List non-superuser accounts with field-backed search and filters."""
    users = User.objects.filter(is_superuser=False).exclude(role=User.Role.ADMIN).order_by("-date_joined", "-pk")
    search = request.GET.get("q", "").strip()
    role = request.GET.get("role", "").strip()
    status = request.GET.get("status", "").strip()

    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
        )
    allowed_roles = {choice[0] for choice in User.Role.choices if choice[0] != User.Role.ADMIN}
    if role in allowed_roles:
        users = users.filter(role=role)
    elif role:
        role = ""

    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    else:
        status = ""

    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "users": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "search_query": search,
        "selected_role": role,
        "selected_status": status,
        "role_choices": tuple(choice for choice in User.Role.choices if choice[0] != User.Role.ADMIN),
        "total_users_count": User.objects.filter(is_superuser=False).exclude(role=User.Role.ADMIN).count(),
        "active_users_count": User.objects.filter(is_superuser=False, is_active=True).exclude(role=User.Role.ADMIN).count(),
        "inactive_users_count": User.objects.filter(is_superuser=False, is_active=False).exclude(role=User.Role.ADMIN).count(),
    }
    return render(request, "users/list.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def user_form(request, user_id=None):
    """Create a limited-role account or edit a non-superuser account."""
    user_obj = None
    if user_id is not None:
        user_obj = get_object_or_404(User, pk=user_id, is_superuser=False)
        # Do not edit an account whose role is intentionally outside this UI.
        if user_obj.role == User.Role.ADMIN:
            return HttpResponseForbidden("This account cannot be managed from this screen.")

    form_class = UserAdminUpdateForm if user_obj else UserAdminCreateForm
    if request.method == "POST":
        form = form_class(request.POST, request.FILES, instance=user_obj) if user_obj else form_class(request.POST, request.FILES)
        if form.is_valid():
            saved_user = form.save()
            messages.success(
                request,
                "User updated successfully." if user_obj else "User created successfully.",
            )
            return redirect("admin_panel:user_list")
    else:
        form = form_class(instance=user_obj) if user_obj else form_class()

    return render(request, "users/form.html", {"form": form, "user_obj": user_obj})


@admin_required
@require_POST
def user_toggle_active(request, user_id):
    """Activate/deactivate a managed account through a CSRF-protected POST."""
    if user_id == request.user.pk:
        messages.error(request, "You cannot deactivate your own account from this screen.")
        return redirect("admin_panel:user_list")
    user_obj = get_object_or_404(User, pk=user_id, is_superuser=False)
    if user_obj.role == User.Role.ADMIN:
        return HttpResponseForbidden("This account cannot be managed from this screen.")

    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=["is_active"])
    messages.success(
        request,
        "User activated successfully." if user_obj.is_active else "User deactivated successfully.",
    )
    return redirect("admin_panel:user_list")


# ==================================================
# COURSES
# ==================================================

@admin_required
@require_GET
def course_dashboard(request):
    """List real courses with validated search/filter parameters and pagination."""
    courses = Course.objects.select_related("instructor", "center").order_by("-created_at", "-pk")
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    mode = request.GET.get("mode", "").strip()
    status = request.GET.get("status", "").strip()
    instructor_id = request.GET.get("instructor", "").strip()

    if search:
        courses = courses.filter(
            Q(title__icontains=search)
            | Q(slug__icontains=search)
            | Q(category__icontains=search)
            | Q(instructor__first_name__icontains=search)
            | Q(instructor__last_name__icontains=search)
            | Q(instructor__email__icontains=search)
        )
    if category:
        courses = courses.filter(category__iexact=category)
    if mode in Course.Mode.values:
        courses = courses.filter(mode=mode)
    elif mode:
        mode = ""
    if status in Course.Status.values:
        courses = courses.filter(status=status)
    elif status:
        status = ""
    if instructor_id:
        if instructor_id.isdigit():
            courses = courses.filter(instructor_id=int(instructor_id))
        else:
            instructor_id = ""

    paginator = Paginator(courses, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "courses": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "search_query": search,
        "selected_category": category,
        "selected_mode": mode,
        "selected_status": status,
        "selected_instructor": instructor_id,
        "categories": Course.objects.exclude(category="").exclude(category__isnull=True).values_list("category", flat=True).distinct().order_by("category"),
        "instructors": User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True).order_by("first_name", "last_name", "email"),
        "total_courses_count": Course.objects.count(),
        "published_courses_count": Course.objects.filter(status=Course.Status.PUBLISHED).count(),
        "draft_courses_count": Course.objects.filter(status=Course.Status.DRAFT).count(),
        "online_courses_count": Course.objects.filter(mode=Course.Mode.ONLINE).count(),
        "offline_courses_count": Course.objects.filter(mode=Course.Mode.OFFLINE).count(),
    }
    return render(request, "courses/dashboard.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def course_form(request, course_id=None):
    """Create/edit a course; publication changes only through explicit form actions."""
    course = get_object_or_404(Course, pk=course_id) if course_id is not None else None

    if request.method == "POST":
        action = request.POST.get("action", "save_draft")
        allowed_actions = {"save_draft", "save_continue", "publish"}
        if action not in allowed_actions:
            messages.error(request, "Unsupported course action. Please use one of the available save buttons.")
            form = CourseAdminForm(request.POST, request.FILES, instance=course)
        else:
            form = CourseAdminForm(request.POST, request.FILES, instance=course)
            if form.is_valid():
                course = form.save(commit=False)
                if action == "publish":
                    course.status = Course.Status.PUBLISHED
                elif action == "save_draft":
                    course.status = Course.Status.DRAFT
                # save_continue deliberately preserves the existing status; new courses
                # retain the model's default draft status. Status is not a form field.
                course.save()
                form.save_m2m()
                if action == "publish":
                    messages.success(request, "Course published successfully.")
                elif action == "save_draft":
                    messages.success(request, "Course saved as draft.")
                else:
                    messages.success(request, "Course saved. You can continue editing.")
                if action == "save_continue":
                    return redirect("admin_panel:course_form", course_id=course.pk)
                return redirect("admin_panel:course_dashboard")
    else:
        form = CourseAdminForm(instance=course)

    return render(request, "courses/form.html", {"form": form, "course": course})


# ==================================================
# SYLLABUS
# ==================================================
@admin_required
@require_GET
def syllabus_course_list(request):
    return render(
        request,
        "syllabus/courselist.html",
    )


@admin_required
@require_GET
def syllabus_curriculum(request):
    return render(
        request,
        "syllabus/curriculum.html",
    )


@admin_required
@require_GET
def syllabus_media_lesson(request):
    return render(
        request,
        "syllabus/media_lesson.html",
    )


# ==================================================
# ENROLLMENTS
# ==================================================
@admin_required
@require_GET
def enrollment_list(request):
    return render(
        request,
        "enrollments/enroll_list.html",
    )


# ==================================================
# PAYMENTS
# ==================================================
@admin_required
@require_GET
def payment_list(request):
    return render(
        request,
        "payments/list.html",
    )

@admin_required
@require_GET
def payment_installments(request):
    return render(
        request,
        "payments/installments.html",
    )


# ==================================================
# BATCHES
# ==================================================
@admin_required
@require_GET
def batch_list(request):
    return render(
        request,
        "batches/list.html",
    )

@admin_required
@require_GET
def batch_sessions(request):
    return render(
        request,
        "batches/sessions.html",
    )

@admin_required
@require_GET
def batch_attendance(request):
    return render(
        request,
        "batches/attendance.html",
    )


# ==================================================
# ASSESSMENTS
# ==================================================
@admin_required
@require_GET
def assessment_list(request):
    return render(
        request,
        "assessments/list.html",
    )

@admin_required
@require_GET
def assessment_questions(request):
    return render(
        request,
        "assessments/questions.html",
    )

@admin_required
@require_GET
def assessment_submissions(request):
    return render(
        request,
        "assessments/submissions.html",
    )


# ==================================================
# DOUBTS
# ==================================================
@admin_required
@require_GET
def doubt_list(request):
    return render(
        request,
        "doubts/list.html",
    )


# ==================================================
# NOTIFICATIONS
# ==================================================
@admin_required
@require_GET
def notification_list(request):
    return render(
        request,
        "notifications/list.html",
    )


# ==================================================
# CONSULTATIONS
# ==================================================
@admin_required
@require_GET
def consultation_list(request):
    return render(
        request,
        "consultations/list.html",
    )


# ==================================================
# CERTIFICATES
# ==================================================
@admin_required
@require_GET
def certificate_list(request):
    return render(
        request,
        "certificates/list.html",
    )


# ==================================================
# REPORTS
# ==================================================

@admin_required
@require_GET
def report_dashboard(request):
    return render(
        request,
        "reports/dashboard.html",
    )


# ==================================================
# SECURITY
# ==================================================
@admin_required
@require_GET
def security_dashboard(request):
    return render(
        request,
        "security/dashboard.html",
    )
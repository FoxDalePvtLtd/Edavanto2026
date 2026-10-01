from django.shortcuts import render

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Course
from .forms import *
from django.views.decorators.http import require_GET, require_http_methods

from .permissions import admin_required


@admin_required
@require_GET
def dashboard(request):
    return render(
        request,
        "dashboard.html",
    )


# ==================================================
# USERS
# ==================================================

@admin_required
@require_GET
def user_list(request):
    return render(
        request,
        "users/list.html",
    )


@admin_required
@require_GET
def user_form(request):
    return render(
        request,
        "users/form.html",
    )


# ==================================================
# COURSES
# ==================================================

@admin_required
@require_GET
def course_dashboard(request):
    courses = Course.objects.all().order_by("-created_at")

    return render(
        request,
        "courses/dashboard.html",
        {
            "courses": courses,
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def course_form(request, course_id=None):

    course = None

    if course_id is not None:
        course = get_object_or_404(
            Course,
            pk=course_id,
        )

    if request.method == "POST":

        form = CourseAdminForm(
            request.POST,
            request.FILES,
            instance=course,
        )

        if form.is_valid():

            course = form.save()

            action = request.POST.get(
                "action",
                "save_draft",
            )

            if action == "publish":
                course.status = Course.Status.PUBLISHED
                course.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Course published successfully.",
                )

            elif action == "save_draft":
                course.status = Course.Status.DRAFT
                course.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Course saved as draft.",
                )

            else:
                messages.success(
                    request,
                    "Course saved successfully.",
                )

            if action == "save_continue":
                return redirect(
                    "admin_panel:course_form",
                    course_id=course.id,
                )

            return redirect(
                "admin_panel:course_dashboard"
            )

    else:

        form = CourseAdminForm(
            instance=course,
        )

    return render(
        request,
        "courses/form.html",
        {
            "form": form,
            "course": course,
        },
    )


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
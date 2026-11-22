from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from center_panel.forms import (
    CenterBatchForm,
    CenterCourseForm,
    CenterInstructorForm,
    CenterLessonForm,
    CenterModuleForm,
)
from center_panel.permissions import center_required
from core.center_services import (
    add_instructor_to_center,
    assign_course_instructor,
)
from core.models import (
    Attendance,
    Batch,
    BatchSession,
    CenterInstructor,
    CenterSubscription,
    CenterSubscriptionPayment,
    Course,
    DoubtThread,
    Enrollment,
    Lesson,
    LessonMaterial,
    Module,
    Notification,
    NotificationDelivery,
    Resource,
    User,
    VideoAsset,
)
from core.services.notification import create_admin_notification


# ============================================================
# 1. CENTER DASHBOARD
# ============================================================

@center_required
@require_GET
def dashboard(request):
    """
    Main dashboard for authenticated center operations.
    Displays real aggregate metrics for the center.
    """
    center = request.center
    now = timezone.now()

    courses = Course.objects.filter(center=center)
    total_courses = courses.count()
    published_courses = courses.filter(status=Course.Status.PUBLISHED).count()
    draft_courses = courses.filter(status=Course.Status.DRAFT).count()
    pending_approval_courses = courses.filter(approval_status=Course.ApprovalStatus.PENDING).count()
    rejected_courses = courses.filter(approval_status=Course.ApprovalStatus.REJECTED).count()

    total_instructors = CenterInstructor.objects.filter(center=center, is_active=True).count()
    total_enrolled_students = (
        Enrollment.objects
        .filter(course__center=center)
        .values("student_id")
        .distinct()
        .count()
    )

    active_batches = Batch.objects.filter(center=center, status=Batch.Status.ACTIVE).count()
    subscription = request.subscription

    recent_courses = courses.order_by("-updated_at")[:5]
    recent_enrollments = (
        Enrollment.objects
        .filter(course__center=center)
        .select_related("student", "course")
        .order_by("-enrolled_at")[:5]
    )

    context = {
        "center": center,
        "subscription": subscription,
        "total_courses": total_courses,
        "published_courses": published_courses,
        "draft_courses": draft_courses,
        "pending_approval_courses": pending_approval_courses,
        "rejected_courses": rejected_courses,
        "total_instructors": total_instructors,
        "total_enrolled_students": total_enrolled_students,
        "active_batches": active_batches,
        "recent_courses": recent_courses,
        "recent_enrollments": recent_enrollments,
        "page_title": "Center Dashboard",
    }
    return render(request, "center_panel/dashboard.html", context)


# ============================================================
# 2. CENTER COURSE MANAGEMENT
# ============================================================

@center_required
@require_GET
def course_list(request):
    """
    List courses owned exclusively by this center.
    """
    center = request.center
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    approval_filter = request.GET.get("approval", "").strip()

    qs = (
        Course.objects
        .filter(center=center)
        .select_related("instructor")
        .prefetch_related("modules")
        .order_by("-updated_at")
    )

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if approval_filter:
        qs = qs.filter(approval_status=approval_filter)

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "center": center,
        "courses": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "approval_filter": approval_filter,
        "status_choices": Course.Status.choices,
        "approval_choices": Course.ApprovalStatus.choices,
        "page_title": "My Courses",
    }
    return render(request, "center_panel/course_list.html", context)


@center_required
@require_http_methods(["GET", "POST"])
def course_create(request):
    """
    Create a new course owned by this center.
    Initial approval status is always DRAFT.
    """
    center = request.center

    if request.method == "POST":
        form = CenterCourseForm(request.POST, request.FILES, center=center)
        action = request.POST.get("action", "save_draft")

        if form.is_valid():
            course = form.save(commit=False)
            course.center = center
            course.approval_status = Course.ApprovalStatus.DRAFT

            if action == "publish":
                # Center can NEVER publish an unapproved course
                messages.error(
                    request,
                    "New center courses cannot be published directly. Please submit your course for admin approval first.",
                )
                course.status = Course.Status.DRAFT
            elif action == "submit_approval":
                course.status = Course.Status.DRAFT
                course.approval_status = Course.ApprovalStatus.PENDING
            else:
                course.status = Course.Status.DRAFT

            course.save()
            form.save_m2m()

            if action == "submit_approval":
                # Notify administrators
                admins = User.objects.filter(is_active=True).filter(
                    Q(is_superuser=True) | Q(role=User.Role.ADMIN)
                ).distinct()
                for admin_user in admins:
                    create_admin_notification(
                        recipient=admin_user,
                        title="New Center Course Submitted for Review",
                        message=f"Center '{center.name}' submitted course '{course.title}' for review.",
                        n_type=Notification.NotificationType.COURSE,
                    )
                messages.success(request, f"Course '{course.title}' submitted for administrator review.")
                return redirect("center_panel:course_list")

            messages.success(request, f"Course '{course.title}' saved as draft.")
            if action == "save_continue":
                return redirect("center_panel:syllabus_curriculum", course_id=course.id)
            return redirect("center_panel:course_list")
    else:
        form = CenterCourseForm(center=center)

    context = {
        "form": form,
        "center": center,
        "page_title": "Add New Course",
    }
    return render(request, "center_panel/course_form.html", context)


@center_required
@require_http_methods(["GET", "POST"])
def course_edit(request, course_id):
    """
    Edit an existing center course.
    Enforces that centers can only publish after administrator approval.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)

    if request.method == "POST":
        form = CenterCourseForm(request.POST, request.FILES, instance=course, center=center)
        action = request.POST.get("action", "save_draft")

        if form.is_valid():
            course = form.save(commit=False)
            course.center = center  # Safety guarantee

            if action == "publish":
                # CRITICAL APPROVAL RULE: Deny publishing if not approved
                if course.approval_status != Course.ApprovalStatus.APPROVED:
                    messages.error(
                        request,
                        "Permission Denied: This course cannot be published until approved by an administrator.",
                    )
                    course.status = Course.Status.DRAFT
                else:
                    course.status = Course.Status.PUBLISHED
                    messages.success(request, f"Course '{course.title}' published successfully.")
            elif action == "submit_approval":
                course.status = Course.Status.DRAFT
                course.approval_status = Course.ApprovalStatus.PENDING
                admins = User.objects.filter(is_active=True).filter(
                    Q(is_superuser=True) | Q(role=User.Role.ADMIN)
                ).distinct()
                for admin_user in admins:
                    create_admin_notification(
                        recipient=admin_user,
                        title="Center Course Resubmitted for Review",
                        message=f"Center '{center.name}' resubmitted course '{course.title}' for review.",
                        n_type=Notification.NotificationType.COURSE,
                    )
                messages.success(request, f"Course '{course.title}' submitted for administrator review.")
            elif action == "unpublish":
                course.status = Course.Status.DRAFT
                messages.info(request, f"Course '{course.title}' moved to draft.")
            else:
                messages.success(request, f"Course '{course.title}' updated.")

            course.save()
            form.save_m2m()

            if action == "save_continue":
                return redirect("center_panel:course_edit", course_id=course.id)
            return redirect("center_panel:course_list")
    else:
        form = CenterCourseForm(instance=course, center=center)

    context = {
        "form": form,
        "course": course,
        "center": center,
        "page_title": f"Edit Course: {course.title}",
    }
    return render(request, "center_panel/course_form.html", context)


@center_required
@require_POST
def course_submit_approval(request, course_id):
    """
    Explicitly submit a course for administrator review.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)

    course.approval_status = Course.ApprovalStatus.PENDING
    course.status = Course.Status.DRAFT
    course.save(update_fields=["approval_status", "status", "updated_at"])

    admins = User.objects.filter(is_active=True).filter(
        User.objects.filter(is_superuser=True) | User.objects.filter(role=User.Role.ADMIN)
    ).distinct()
    for admin_user in admins:
        create_admin_notification(
            recipient=admin_user,
            title="Center Course Submitted for Approval",
            message=f"Center '{center.name}' submitted course '{course.title}' for review.",
            n_type=Notification.NotificationType.COURSE,
        )

    messages.success(request, f"Course '{course.title}' has been submitted for administrator approval.")
    return redirect("center_panel:course_list")


# ============================================================
# 3. CENTER SYLLABUS, MODULES & LESSONS MANAGEMENT
# ============================================================

@center_required
@require_GET
def syllabus_curriculum(request, course_id):
    """
    Curriculum builder workspace for a center's course.
    """
    center = request.center
    course = get_object_or_404(
        Course.objects.prefetch_related("modules__lessons__materials", "modules__lessons__video_asset"),
        pk=course_id,
        center=center,
    )
    modules = course.modules.all().order_by("order", "pk")

    context = {
        "center": center,
        "course": course,
        "modules": modules,
        "page_title": f"Curriculum: {course.title}",
    }
    return render(request, "center_panel/syllabus_curriculum.html", context)


@center_required
@require_http_methods(["GET", "POST"])
def module_create(request, course_id):
    """
    Add a module to a center course.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)

    if request.method == "POST":
        form = CenterModuleForm(request.POST)
        if form.is_valid():
            module = form.save(commit=False)
            module.course = course
            module.save()
            messages.success(request, f"Module '{module.title}' added.")
            return redirect("center_panel:syllabus_curriculum", course_id=course.id)
    else:
        next_order = (course.modules.count() + 1)
        form = CenterModuleForm(initial={"order": next_order, "unlock_order": next_order})

    return render(
        request,
        "center_panel/module_form.html",
        {"form": form, "course": course, "page_title": "Add Module"},
    )


@center_required
@require_http_methods(["GET", "POST"])
def module_edit(request, course_id, module_id):
    """
    Edit a module of a center course.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)
    module = get_object_or_404(Module, pk=module_id, course=course)

    if request.method == "POST":
        form = CenterModuleForm(request.POST, instance=module)
        if form.is_valid():
            form.save()
            messages.success(request, f"Module '{module.title}' updated.")
            return redirect("center_panel:syllabus_curriculum", course_id=course.id)
    else:
        form = CenterModuleForm(instance=module)

    return render(
        request,
        "center_panel/module_form.html",
        {"form": form, "course": course, "module": module, "page_title": f"Edit {module.title}"},
    )


@center_required
@require_POST
def module_delete(request, course_id, module_id):
    """
    Delete a module from a center course.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)
    module = get_object_or_404(Module, pk=module_id, course=course)
    title = module.title
    module.delete()
    messages.info(request, f"Module '{title}' deleted.")
    return redirect("center_panel:syllabus_curriculum", course_id=course.id)


@center_required
@require_http_methods(["GET", "POST"])
def lesson_create(request, course_id, module_id):
    """
    Add a lesson to a center module.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)
    module = get_object_or_404(Module, pk=module_id, course=course)

    if request.method == "POST":
        form = CenterLessonForm(request.POST)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.module = module
            lesson.save()
            messages.success(request, f"Lesson '{lesson.title}' created.")
            return redirect("center_panel:syllabus_curriculum", course_id=course.id)
    else:
        next_order = (module.lessons.count() + 1)
        form = CenterLessonForm(initial={"order": next_order, "unlock_order": next_order})

    return render(
        request,
        "center_panel/lesson_form.html",
        {"form": form, "course": course, "module": module, "page_title": "Add Lesson"},
    )


@center_required
@require_http_methods(["GET", "POST"])
def lesson_edit(request, course_id, module_id, lesson_id):
    """
    Edit a lesson.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    if request.method == "POST":
        form = CenterLessonForm(request.POST, instance=lesson)
        if form.is_valid():
            form.save()
            messages.success(request, f"Lesson '{lesson.title}' updated.")
            return redirect("center_panel:syllabus_curriculum", course_id=course.id)
    else:
        form = CenterLessonForm(instance=lesson)

    return render(
        request,
        "center_panel/lesson_form.html",
        {"form": form, "course": course, "module": module, "lesson": lesson, "page_title": f"Edit {lesson.title}"},
    )


@center_required
@require_POST
def lesson_delete(request, course_id, module_id, lesson_id):
    """
    Delete a lesson.
    """
    center = request.center
    course = get_object_or_404(Course, pk=course_id, center=center)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)
    title = lesson.title
    lesson.delete()
    messages.info(request, f"Lesson '{title}' deleted.")
    return redirect("center_panel:syllabus_curriculum", course_id=course.id)


# ============================================================
# 4. INSTRUCTOR MANAGEMENT & ASSIGNMENT
# ============================================================

@center_required
@require_GET
def instructor_list(request):
    """
    List instructors registered with this center.
    """
    center = request.center
    memberships = (
        CenterInstructor.objects
        .filter(center=center)
        .select_related("instructor")
        .prefetch_related("instructor__courses_taught")
        .order_by("-joined_at")
    )

    context = {
        "center": center,
        "memberships": memberships,
        "page_title": "Center Instructors",
    }
    return render(request, "center_panel/instructor_list.html", context)


@center_required
@require_http_methods(["GET", "POST"])
def instructor_add(request):
    """
    Register and associate a new or existing instructor with this center.
    """
    center = request.center

    if request.method == "POST":
        form = CenterInstructorForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            try:
                membership = add_instructor_to_center(
                    center=center,
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    email=data["email"],
                    phone=data["phone"],
                    specialization=data["specialization"],
                    password=data.get("password"),
                    profile_photo=data.get("profile_photo"),
                )
                messages.success(
                    request,
                    f"Instructor '{membership.instructor.get_full_name() or membership.instructor.username}' added to your center.",
                )
                return redirect("center_panel:instructor_list")
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = CenterInstructorForm()

    return render(
        request,
        "center_panel/instructor_form.html",
        {"form": form, "center": center, "page_title": "Add Instructor"},
    )


@center_required
@require_POST
def instructor_toggle_active(request, membership_id):
    """
    Activate or deactivate an instructor's association with this center.
    """
    center = request.center
    membership = get_object_or_404(CenterInstructor, pk=membership_id, center=center)
    membership.is_active = not membership.is_active
    membership.save(update_fields=["is_active", "updated_at"])

    status_str = "activated" if membership.is_active else "deactivated"
    messages.info(request, f"Instructor association {status_str}.")
    return redirect("center_panel:instructor_list")


# ============================================================
# 5. STUDENTS & ENROLLMENT MANAGEMENT
# ============================================================

@center_required
@require_GET
def student_list(request):
    """
    List students enrolled in this center's courses.
    """
    center = request.center
    search_query = request.GET.get("q", "").strip()

    enrollments = (
        Enrollment.objects
        .filter(course__center=center)
        .select_related("student", "course")
        .order_by("-enrolled_at")
    )

    if search_query:
        enrollments = enrollments.filter(
            Q(student__first_name__icontains=search_query) |
            Q(student__last_name__icontains=search_query) |
            Q(student__email__icontains=search_query) |
            Q(course__title__icontains=search_query)
        )

    paginator = Paginator(enrollments, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "center": center,
        "enrollments": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": search_query,
        "page_title": "Center Students & Enrollments",
    }
    return render(request, "center_panel/student_list.html", context)


# ============================================================
# 6. BATCHES & ATTENDANCE
# ============================================================

@center_required
@require_GET
def batch_list(request):
    """
    List batches created for this center.
    """
    center = request.center
    batches = (
        Batch.objects
        .filter(center=center)
        .select_related("course", "instructor")
        .prefetch_related("sessions")
        .order_by("-created_at")
    )

    context = {
        "center": center,
        "batches": batches,
        "page_title": "Center Batches",
    }
    return render(request, "center_panel/batch_list.html", context)


@center_required
@require_http_methods(["GET", "POST"])
def batch_create(request):
    """
    Create a new batch for center courses.
    """
    center = request.center

    if request.method == "POST":
        form = CenterBatchForm(request.POST, center=center)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.center = center
            batch.save()
            messages.success(request, f"Batch '{batch.name}' created.")
            return redirect("center_panel:batch_list")
    else:
        form = CenterBatchForm(center=center)

    return render(
        request,
        "center_panel/batch_form.html",
        {"form": form, "center": center, "page_title": "Create Batch"},
    )


@center_required
@require_GET
def batch_attendance(request):
    """
    View attendance records across center batches.
    """
    center = request.center
    records = (
        Attendance.objects
        .filter(session__batch__center=center)
        .select_related("student", "session__batch", "marked_by")
        .order_by("-marked_at")[:50]
    )

    context = {
        "center": center,
        "records": records,
        "page_title": "Batch Attendance Overview",
    }
    return render(request, "center_panel/attendance_overview.html", context)


# ============================================================
# 7. DOUBTS OVERVIEW (READ-ONLY)
# ============================================================

@center_required
@require_GET
def doubt_overview(request):
    """
    Read-only overview of doubts asked for this center's courses.
    """
    center = request.center
    doubts = (
        DoubtThread.objects
        .filter(enrollment__course__center=center)
        .select_related("student", "lesson", "enrollment__course", "assigned_instructor")
        .order_by("-created_at")[:50]
    )

    context = {
        "center": center,
        "doubts": doubts,
        "page_title": "Doubts Overview",
    }
    return render(request, "center_panel/doubt_overview.html", context)


# ============================================================
# 8. SUBSCRIPTION & CENTER PROFILE
# ============================================================

@center_required(require_subscription=False)
@require_GET
def subscription_status(request):
    """
    Subscription details, active status, days remaining, and renewal option.
    Accessible even if subscription has expired so the center can renew!
    """
    center = request.center
    subscription = center.get_active_subscription()
    all_subscriptions = center.subscriptions.select_related("plan").all().order_by("-created_at")
    payments = (
        CenterSubscriptionPayment.objects
        .filter(subscription__center=center)
        .select_related("subscription__plan")
        .order_by("-created_at")
    )

    context = {
        "center": center,
        "subscription": subscription,
        "all_subscriptions": all_subscriptions,
        "payments": payments,
        "page_title": "Subscription Management",
    }
    return render(request, "center_panel/subscription_status.html", context)


@center_required(require_subscription=False)
@require_http_methods(["GET", "POST"])
def profile(request):
    """
    Center profile and owner settings.
    """
    center = request.center

    if request.method == "POST":
        center.contact_number = request.POST.get("contact_number", "").strip()
        center.address = request.POST.get("address", "").strip()
        center.city = request.POST.get("city", "").strip()
        center.state = request.POST.get("state", "").strip()
        center.postal_code = request.POST.get("postal_code", "").strip()
        center.website = request.POST.get("website", "").strip()
        center.description = request.POST.get("description", "").strip()
        center.save()

        # Update owner user info
        if center.owner:
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            phone = request.POST.get("owner_phone", "").strip()
            center.owner.first_name = first_name
            center.owner.last_name = last_name
            center.owner.phone = phone
            center.owner.save(update_fields=["first_name", "last_name", "phone"])

        messages.success(request, "Center profile updated successfully.")
        return redirect("center_panel:profile")

    context = {
        "center": center,
        "page_title": "Center Profile",
    }
    return render(request, "center_panel/profile.html", context)

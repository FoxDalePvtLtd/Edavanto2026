from django.shortcuts import render

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden

from django.db.models import Q, Sum
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone

from core.models import *
from .forms import *
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .permissions import admin_required
from core.services.video_probe import probe_video

def _dbg(msg):
    """Single-line debug helper — visible in runserver console."""
    print(f"[ADMIN-PANEL] {msg}")


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
# USERS

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
# COURSES

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
# SYLLABUS / CURRICULUM

@admin_required
@require_GET
def syllabus_course_list(request):
    """List all courses so admin can pick one to manage its curriculum."""
    courses = (
        Course.objects
        .prefetch_related("modules")
        .order_by("title", "pk")
    )

    search = request.GET.get("q", "").strip()
    if search:
        courses = courses.filter(
            Q(title__icontains=search) | Q(slug__icontains=search)
        )

    paginator = Paginator(courses, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "courses": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "search_query": search,
        "page_title": "Syllabus",
    }
    return render(request, "syllabus/courselist.html", context)


@admin_required
@require_GET
def syllabus_curriculum(request, course_id):
    """Show all modules and their lessons for one course."""
    _dbg(f"syllabus_curriculum: course_id={course_id} user={request.user}")

    course = get_object_or_404(
        Course.objects.prefetch_related(
            "modules__lessons",
        ),
        pk=course_id,
    )

    modules = course.modules.all().order_by("order", "pk")

    # Build a JSON-friendly list of {module, lessons[]} for the JS workspace.
    modules_payload = []
    for m in modules:
        lessons_qs = m.lessons.all().order_by("order", "pk")
        modules_payload.append({
            "id": m.pk,
            "title": m.title,
            "description": m.description,
            "order": m.order,
            "unlock_order": m.unlock_order,
            "duration_hours": m.duration_hours,
            "duration_weeks": m.duration_weeks,
            "lesson_count": lessons_qs.count(),
            "edit_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/edit/",
            "delete_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/delete/",
            "add_lesson_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/lessons/new/",
            "lessons": [
                {
                    "id": l.pk,
                    "title": l.title,
                    "description": l.description,
                    "order": l.order,
                    "unlock_order": l.unlock_order,
                    "duration_seconds": l.duration_seconds,
                    "status": l.status,
                    "status_display": l.get_status_display(),
                    "is_published": l.is_published,
                    "edit_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/lessons/{l.pk}/edit/",
                    "delete_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/lessons/{l.pk}/delete/",
                    "media_url": f"/admin-panel/syllabus/course/{course.pk}/modules/{m.pk}/lessons/{l.pk}/media/",
                }
                for l in lessons_qs
            ],
        })

    _dbg(f"syllabus_curriculum: course={course.title!r} modules={len(modules_payload)}")

    context = {
        "course": course,
        "modules": modules,
        "modules_payload": modules_payload,
        "module_count": modules.count(),
        "page_title": "Curriculum",
    }
    return render(request, "syllabus/curriculum.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def module_create(request, course_id):
    """Create a module under the selected course."""
    _dbg(f"module_create: method={request.method} course_id={course_id}")
    course = get_object_or_404(Course, pk=course_id)

    if request.method == "POST":
        form = ModuleAdminForm(request.POST, course=course)
        _dbg(f"module_create: POST data={dict(request.POST)}")
        if form.is_valid():
            module = form.save(commit=False)
            module.course = course

            if not form.cleaned_data.get("order"):
                last_order = (
                    Module.objects.filter(course=course)
                    .order_by("-order", "-pk")
                    .values_list("order", flat=True).first()
                )
                module.order = (last_order + 1) if last_order is not None else 1

            if not form.cleaned_data.get("unlock_order"):
                last_unlock = (
                    Module.objects.filter(course=course)
                    .order_by("-unlock_order", "-pk")
                    .values_list("unlock_order", flat=True).first()
                )
                module.unlock_order = (last_unlock + 1) if last_unlock is not None else 1

            module.save()
            _dbg(f"module_create: SAVED id={module.pk} title={module.title!r}")
            messages.success(request, f'Module "{module.title}" was created successfully.')
            return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)
        else:
            _dbg(f"module_create: INVALID form errors={form.errors.as_json()}")
    else:
        last_order = (
            Module.objects.filter(course=course)
            .order_by("-order", "-pk")
            .values_list("order", flat=True).first()
        )
        last_unlock = (
            Module.objects.filter(course=course)
            .order_by("-unlock_order", "-pk")
            .values_list("unlock_order", flat=True).first()
        )
        form = ModuleAdminForm(
            course=course,
            initial={
                "order": (last_order + 1) if last_order is not None else 1,
                "unlock_order": (last_unlock + 1) if last_unlock is not None else 1,
            },
        )

    context = {
        "course": course,
        "form": form,
        "module": None,
        "page_title": "Create Module",
    }
    return render(request, "syllabus/module_form.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def module_edit(request, course_id, module_id):
    """Edit a module only when it belongs to the selected course."""
    _dbg(f"module_edit: method={request.method} course_id={course_id} module_id={module_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)

    if request.method == "POST":
        form = ModuleAdminForm(request.POST, instance=module, course=course)
        if form.is_valid():
            module = form.save()
            _dbg(f"module_edit: SAVED id={module.pk} title={module.title!r}")
            messages.success(request, f'Module "{module.title}" was updated successfully.')
            return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)
        else:
            _dbg(f"module_edit: INVALID form errors={form.errors.as_json()}")
    else:
        form = ModuleAdminForm(instance=module, course=course)

    context = {
        "course": course,
        "form": form,
        "module": module,
        "page_title": "Edit Module",
    }
    return render(request, "syllabus/module_form.html", context)


@admin_required
@require_POST
def module_delete(request, course_id, module_id):
    """Delete a module only when it belongs to the selected course."""
    _dbg(f"module_delete: course_id={course_id} module_id={module_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    module_title = module.title
    module.delete()
    _dbg(f"module_delete: DELETED title={module_title!r}")
    messages.success(request, f'Module "{module_title}" was deleted successfully.')
    return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)
# LESSONS

@admin_required
@require_http_methods(["GET", "POST"])
def lesson_create(request, course_id, module_id):
    """Create a lesson under the selected module."""
    _dbg(f"lesson_create: method={request.method} course_id={course_id} module_id={module_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    _dbg(f"lesson_create: course={course.title!r} module={module.title!r}")

    if request.method == "POST":
        _dbg(f"lesson_create: POST data={dict(request.POST)}")
        form = LessonAdminForm(request.POST, module=module)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.module = module

            if not form.cleaned_data.get("order"):
                last_order = (
                    Lesson.objects.filter(module=module)
                    .order_by("-order", "-pk")
                    .values_list("order", flat=True).first()
                )
                lesson.order = (last_order + 1) if last_order is not None else 1

            if not form.cleaned_data.get("unlock_order"):
                last_unlock = (
                    Lesson.objects.filter(module=module)
                    .order_by("-unlock_order", "-pk")
                    .values_list("unlock_order", flat=True).first()
                )
                lesson.unlock_order = (last_unlock + 1) if last_unlock is not None else 1

            lesson.save()
            _dbg(f"lesson_create: SAVED id={lesson.pk} title={lesson.title!r} module={module.pk}")
            messages.success(request, f'Lesson "{lesson.title}" was created successfully.')
            return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)
        else:
            _dbg(f"lesson_create: INVALID form errors={form.errors.as_json()}")
    else:
        last_order = (
            Lesson.objects.filter(module=module)
            .order_by("-order", "-pk")
            .values_list("order", flat=True).first()
        )
        last_unlock = (
            Lesson.objects.filter(module=module)
            .order_by("-unlock_order", "-pk")
            .values_list("unlock_order", flat=True).first()
        )
        form = LessonAdminForm(
            module=module,
            initial={
                "order": (last_order + 1) if last_order is not None else 1,
                "unlock_order": (last_unlock + 1) if last_unlock is not None else 1,
            },
        )

    context = {
        "course": course,
        "module": module,
        "form": form,
        "lesson": None,
        "page_title": "Create Lesson",
    }
    return render(request, "syllabus/lesson_form.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def lesson_edit(request, course_id, module_id, lesson_id):
    """Edit a lesson only when it belongs to the selected module."""
    _dbg(f"lesson_edit: method={request.method} course={course_id} module={module_id} lesson={lesson_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    if request.method == "POST":
        form = LessonAdminForm(request.POST, instance=lesson, module=module)
        if form.is_valid():
            lesson = form.save()
            _dbg(f"lesson_edit: SAVED id={lesson.pk} title={lesson.title!r}")
            messages.success(request, f'Lesson "{lesson.title}" was updated successfully.')
            return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)
        else:
            _dbg(f"lesson_edit: INVALID form errors={form.errors.as_json()}")
    else:
        form = LessonAdminForm(instance=lesson, module=module)

    context = {
        "course": course,
        "module": module,
        "form": form,
        "lesson": lesson,
        "page_title": "Edit Lesson",
    }
    return render(request, "syllabus/lesson_form.html", context)


@admin_required
@require_POST
def lesson_delete(request, course_id, module_id, lesson_id):
    """Delete a lesson only when it belongs to the selected module."""
    _dbg(f"lesson_delete: course={course_id} module={module_id} lesson={lesson_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)
    lesson_title = lesson.title
    lesson.delete()
    _dbg(f"lesson_delete: DELETED title={lesson_title!r}")
    messages.success(request, f'Lesson "{lesson_title}" was deleted successfully.')
    return redirect("admin_panel:syllabus_curriculum", course_id=course.pk)


@admin_required
@require_GET
def syllabus_media_lesson(request, course_id, module_id, lesson_id):
    """Per-lesson media & resource management page."""
    _dbg(f"syllabus_media_lesson: course={course_id} module={module_id} lesson={lesson_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    video_asset = getattr(lesson, "video_asset", None)
    resources = lesson.resources.all().order_by("-created_at")
    materials = lesson.materials.filter(is_active=True).order_by("title", "pk")

    context = {
        "course": course,
        "module": module,
        "lesson": lesson,
        "video_asset": video_asset,
        "resources": resources,
        "resource_count": materials.count(),
        "materials": materials,
    }
    return render(request, "syllabus/media_lesson.html", context)
# ENROLLMENTS

@admin_required
@require_GET
def enrollment_list(request):
    """List real enrollments with search, filters and pagination."""
    enrollments = (
        Enrollment.objects
        .select_related("student", "course", "course__instructor")
        .order_by("-enrolled_at", "-pk")
    )

    search = request.GET.get("q", "").strip()
    approval = request.GET.get("approval", "").strip()
    payment = request.GET.get("payment", "").strip()
    mode = request.GET.get("mode", "").strip()

    if search:
        enrollments = enrollments.filter(
            Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
            | Q(student__email__icontains=search)
            | Q(student__username__icontains=search)
            | Q(course__title__icontains=search)
        )

    if approval in Enrollment.ApprovalStatus.values:
        enrollments = enrollments.filter(approval_status=approval)
    else:
        approval = ""

    if payment in Enrollment.PaymentStatus.values:
        enrollments = enrollments.filter(payment_status=payment)
    else:
        payment = ""

    if mode in Course.Mode.values:
        enrollments = enrollments.filter(course__mode=mode)
    else:
        mode = ""

    paginator = Paginator(enrollments, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "enrollments": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "search_query": search,
        "selected_approval": approval,
        "selected_payment": payment,
        "selected_mode": mode,
        "approval_choices": Enrollment.ApprovalStatus.choices,
        "payment_choices": Enrollment.PaymentStatus.choices,
        "mode_choices": Course.Mode.choices,
        "total_enrollments_count": Enrollment.objects.count(),
        "pending_approval_count": Enrollment.objects.filter(
            approval_status=Enrollment.ApprovalStatus.PENDING
        ).count(),
        "accepted_count": Enrollment.objects.filter(
            approval_status=Enrollment.ApprovalStatus.ACCEPTED
        ).count(),
        "rejected_count": Enrollment.objects.filter(
            approval_status=Enrollment.ApprovalStatus.REJECTED
        ).count(),
        "paid_count": Enrollment.objects.filter(
            payment_status=Enrollment.PaymentStatus.PAID
        ).count(),
    }
    return render(request, "enrollments/enroll_list.html", context)
# PAYMENTS
@admin_required
@require_GET
def payment_list(request):
    return render(request, "payments/list.html")


@admin_required
@require_GET
def payment_installments(request):
    return render(request, "payments/installments.html")
# BATCHES
@admin_required
@require_GET
def batch_list(request):
    return render(request, "batches/list.html")


@admin_required
@require_GET
def batch_sessions(request):
    return render(request, "batches/sessions.html")


@admin_required
@require_GET
def batch_attendance(request):
    return render(request, "batches/attendance.html")
# ASSESSMENTS
@admin_required
@require_GET
def assessment_list(request):
    return render(request, "assessments/list.html")


@admin_required
@require_GET
def assessment_questions(request):
    return render(request, "assessments/questions.html")


@admin_required
@require_GET
def assessment_submissions(request):
    return render(request, "assessments/submissions.html")
# DOUBTS
@admin_required
@require_GET
def doubt_list(request):
    return render(request, "doubts/list.html")
# NOTIFICATIONS
@admin_required
@require_GET
def notification_list(request):
    return render(request, "notifications/list.html")
# CONSULTATIONS
@admin_required
@require_GET
def consultation_list(request):
    return render(request, "consultations/list.html")
# CERTIFICATES
@admin_required
@require_GET
def certificate_list(request):
    return render(request, "certificates/list.html")
# REPORTS
@admin_required
@require_GET
def report_dashboard(request):
    return render(request, "reports/dashboard.html")
# SECURITY
@admin_required
@require_GET
def security_dashboard(request):
    return render(request, "security/dashboard.html")

import os
from django.core.files.base import ContentFile
from core.services.material_crypto import encrypt_stream
from core.models import LessonMaterial, MaterialAccessLog

@admin_required
@require_http_methods(["GET", "POST"])
def lesson_material_create(request, course_id, module_id, lesson_id):
    _dbg(f"lesson_material_create: method={request.method} course={course_id} module={module_id} lesson={lesson_id}")

    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    if request.method == "POST":
        form = LessonMaterialAdminForm(request.POST, request.FILES)
        _dbg(f"lesson_material_create: POST files={list(request.FILES.keys())}")
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            content_type = (
                form.cleaned_data.get("content_type")
                or uploaded.content_type
                or "application/octet-stream"
            )
            original_name = (
                form.cleaned_data.get("original_filename")
                or uploaded.name
            )

            # Encrypt to a temporary in-memory buffer, then save.
            import io
            buf = io.BytesIO()
            nonce_hex, sha256_hex, size = encrypt_stream(uploaded, buf)
            buf.seek(0)

            material = form.save(commit=False)
            material.lesson = lesson
            material.original_filename = original_name
            material.content_type = content_type
            material.encryption_nonce = nonce_hex
            material.content_sha256 = sha256_hex
            material.size_bytes = size
            material.uploaded_by = request.user

            # Save encrypted bytes to the private storage.
            safe_name = f"{lesson.pk}_{original_name}"
            material.file.save(safe_name, ContentFile(buf.getvalue()), save=False)
            material.save()

            _dbg(f"lesson_material_create: SAVED material id={material.pk} size={size} type={content_type}")
            messages.success(request, f'Material "{material.title}" uploaded.')
            return redirect(
                "admin_panel:syllabus_media_lesson",
                course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
            )
        else:
            _dbg(f"lesson_material_create: INVALID errors={form.errors.as_json()}")

    else:
        form = LessonMaterialAdminForm()

    return render(request, "syllabus/material_form.html", {
        "course": course, "module": module, "lesson": lesson,
        "form": form, "page_title": "Upload Study Material",
    })


@admin_required
@require_POST
def lesson_material_delete(request, course_id, module_id, lesson_id, material_id):
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)
    material = get_object_or_404(LessonMaterial, pk=material_id, lesson=lesson)

    title = material.title
    # Delete the encrypted file from disk too.
    material.file.delete(save=False)
    material.delete()

    messages.success(request, f'Material "{title}" deleted.')
    return redirect(
        "admin_panel:syllabus_media_lesson",
        course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
    )


# ==================================================
# VIDEO ASSET
# ==================================================

from core.services.video_probe import probe_video
from django.utils import timezone


@admin_required
@require_http_methods(["GET", "POST"])
def lesson_video_upload(request, course_id, module_id, lesson_id):
    """Create or replace the single VideoAsset for a lesson."""
    _dbg(f"lesson_video_upload: method={request.method} course={course_id} module={module_id} lesson={lesson_id}")

    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    existing = getattr(lesson, "video_asset", None)

    if request.method == "POST":
        form = VideoAssetAdminForm(request.POST, request.FILES, instance=existing)
        _dbg(f"lesson_video_upload: POST files={list(request.FILES.keys())}")

        if form.is_valid():
            video = form.save(commit=False)
            video.lesson = lesson

            uploaded = request.FILES.get("original_file")
            if uploaded:
                # Best-effort metadata extraction from the raw upload.
                duration, resolution = probe_video(uploaded)
                _dbg(
                    f"lesson_video_upload: probe duration={duration} "
                    f"resolution={resolution!r}"
                )
                # Rewind the file handle — ffprobe consumed it.
                try:
                    uploaded.seek(0)
                except Exception:
                    pass

                if duration:
                    video.duration_seconds = duration
                if resolution:
                    video.resolution = resolution

                # Any new upload starts as Processing unless admin
                # explicitly chose otherwise in the dropdown.
                if video.processing_status not in (
                    VideoAsset.ProcessingStatus.READY,
                    VideoAsset.ProcessingStatus.FAILED,
                ):
                    video.processing_status = VideoAsset.ProcessingStatus.PROCESSING

                video.processed_at = None

            video.save()
            _dbg(
                f"lesson_video_upload: SAVED video id={video.pk} "
                f"status={video.processing_status} "
                f"duration={video.duration_seconds} res={video.resolution!r} "
                f"file={video.original_file.name}"
            )

            messages.success(
                request,
                "Video uploaded. Duration and resolution were detected automatically."
                if uploaded else "Video details updated.",
            )
            return redirect(
                "admin_panel:syllabus_media_lesson",
                course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
            )
        else:
            _dbg(f"lesson_video_upload: INVALID errors={form.errors.as_json()}")

    else:
        form = VideoAssetAdminForm(instance=existing)

    return render(request, "syllabus/video_form.html", {
        "course": course,
        "module": module,
        "lesson": lesson,
        "video_asset": existing,
        "form": form,
        "page_title": "Upload Video" if existing is None else "Replace Video",
    })


@admin_required
@require_POST
def lesson_video_delete(request, course_id, module_id, lesson_id):
    """Delete the VideoAsset attached to a lesson."""
    _dbg(f"lesson_video_delete: course={course_id} module={module_id} lesson={lesson_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)
    video = get_object_or_404(VideoAsset, lesson=lesson)

    # Delete the raw file from storage (best-effort).
    try:
        video.original_file.delete(save=False)
    except Exception as exc:
        _dbg(f"lesson_video_delete: file delete failed: {exc}")

    video.delete()
    messages.success(request, "Video removed from lesson.")
    return redirect(
        "admin_panel:syllabus_media_lesson",
        course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
    )


# ==================================================
# RESOURCE LINKS
# ==================================================

@admin_required
@require_http_methods(["GET", "POST"])
def lesson_resource_create(request, course_id, module_id, lesson_id):
    """Create a Resource (external URL or file) attached to a lesson."""
    _dbg(f"lesson_resource_create: method={request.method} course={course_id} module={module_id} lesson={lesson_id}")

    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)

    if request.method == "POST":
        form = ResourceAdminForm(request.POST, request.FILES)
        _dbg(f"lesson_resource_create: POST files={list(request.FILES.keys())}")
        if form.is_valid():
            resource = form.save(commit=False)
            resource.lesson = lesson
            resource.save()
            _dbg(f"lesson_resource_create: SAVED resource id={resource.pk} title={resource.title!r}")
            messages.success(request, f'Resource "{resource.title}" added.')
            return redirect(
                "admin_panel:syllabus_media_lesson",
                course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
            )
        else:
            _dbg(f"lesson_resource_create: INVALID errors={form.errors.as_json()}")

    else:
        form = ResourceAdminForm()

    return render(request, "syllabus/resource_form.html", {
        "course": course,
        "module": module,
        "lesson": lesson,
        "form": form,
        "page_title": "Add Resource Link",
    })


@admin_required
@require_POST
def lesson_resource_delete(request, course_id, module_id, lesson_id, resource_id):
    """Delete a Resource attached to a lesson."""
    _dbg(f"lesson_resource_delete: course={course_id} module={module_id} lesson={lesson_id} resource={resource_id}")
    course = get_object_or_404(Course, pk=course_id)
    module = get_object_or_404(Module, pk=module_id, course=course)
    lesson = get_object_or_404(Lesson, pk=lesson_id, module=module)
    resource = get_object_or_404(Resource, pk=resource_id, lesson=lesson)

    title = resource.title
    # Best-effort file removal.
    if resource.file:
        try:
            resource.file.delete(save=False)
        except Exception as exc:
            _dbg(f"lesson_resource_delete: file delete failed: {exc}")

    resource.delete()
    messages.success(request, f'Resource "{title}" removed.')
    return redirect(
        "admin_panel:syllabus_media_lesson",
        course_id=course.pk, module_id=module.pk, lesson_id=lesson.pk,
    )
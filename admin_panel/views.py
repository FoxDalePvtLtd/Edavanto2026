from core.services.payments import approve_offline_payment, reject_offline_payment
from core.services.enrollment import approve_enrollment, reject_enrollment
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse
from decimal import Decimal
import json

from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone

from core.models import *
from .forms import *
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .permissions import admin_required
from core.services.video_probe import probe_video
from django.contrib.auth.decorators import login_required
from .views_centers import *

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
    # Attach latest order for offline info
    enrollment_list_objs = list(page_obj.object_list)
    student_ids = [e.student_id for e in enrollment_list_objs]
    course_ids = [e.course_id for e in enrollment_list_objs]
    orders = (
        Order.objects
        .filter(student_id__in=student_ids, course_id__in=course_ids)
        .prefetch_related("transactions")
        .order_by("-created_at")
    )
    order_map = {}
    for o in orders:
        key = (o.student_id, o.course_id)
        if key not in order_map:
            order_map[key] = o
            o.latest_txn = o.transactions.order_by("-created_at").first()

    for e in enrollment_list_objs:
        e.order = order_map.get((e.student_id, e.course_id))

    context["enrollments"] = enrollment_list_objs
    return render(request, "enrollments/enroll_list.html", context)


@admin_required
@require_POST
def enrollment_approve(request, enrollment_id):
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("student", "course"),
        pk=enrollment_id,
    )
    offline_order = (
        Order.objects
        .filter(
            student=enrollment.student,
            course=enrollment.course,
            payment_method=Order.PaymentMethod.OFFLINE,
        )
        .exclude(status=Order.Status.PAID)
        .order_by("-created_at")
        .first()
    )

    try:
        if offline_order:
            approve_offline_payment(order=offline_order, approved_by=request.user)
            messages.success(
                request,
                f"Offline payment for '{enrollment.student.get_full_name() or enrollment.student.username}' on '{enrollment.course.title}' approved successfully! Course access activated."
            )
        else:
            approve_enrollment(enrollment=enrollment, approved_by=request.user)
            messages.success(
                request,
                f"Enrollment for '{enrollment.student.get_full_name() or enrollment.student.username}' on '{enrollment.course.title}' has been approved."
            )
    except Exception as exc:
        messages.error(request, f"Approval error: {exc}")

    return redirect("admin_panel:enrollment_list")


@admin_required
@require_POST
def enrollment_reject(request, enrollment_id):
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("student", "course"),
        pk=enrollment_id,
    )
    reason = request.POST.get("reason", "Offline payment request rejected by administrator.").strip()

    offline_order = (
        Order.objects
        .filter(
            student=enrollment.student,
            course=enrollment.course,
            payment_method=Order.PaymentMethod.OFFLINE,
        )
        .exclude(status=Order.Status.PAID)
        .order_by("-created_at")
        .first()
    )

    try:
        if offline_order:
            reject_offline_payment(order=offline_order, rejected_by=request.user, reason=reason)
            messages.warning(
                request,
                f"Offline payment request for '{enrollment.student.get_full_name() or enrollment.student.username}' was rejected."
            )
        else:
            reject_enrollment(enrollment=enrollment, rejected_by=request.user, reason=reason)
            messages.warning(
                request,
                f"Enrollment for '{enrollment.student.get_full_name() or enrollment.student.username}' was rejected."
            )
    except Exception as exc:
        messages.error(request, f"Rejection error: {exc}")

    return redirect("admin_panel:enrollment_list")


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
@require_http_methods(["GET", "POST"])
def assessment_list(request):
    """List assessments with real filtering, pagination, and handle new assessment creation."""
    if request.method == "POST":
        module_id = request.POST.get("module")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        assessment_type = request.POST.get("assessment_type", Assessment.AssessmentType.QUIZ)
        unlock_order = int(request.POST.get("unlock_order") or 0)
        total_marks = int(request.POST.get("total_marks") or 0)
        pass_percentage = int(request.POST.get("pass_percentage") or 50)
        time_limit_minutes = request.POST.get("time_limit_minutes")
        time_limit_minutes = int(time_limit_minutes) if time_limit_minutes else None
        attempts_allowed = int(request.POST.get("attempts_allowed") or 1)
        due_date_raw = request.POST.get("due_date", "").strip()
        due_date = None
        if due_date_raw:
            try:
                due_date = timezone.datetime.fromisoformat(due_date_raw)
            except Exception:
                due_date = None
        is_published = request.POST.get("is_published") in ["true", "True", "on", "1"]

        module = get_object_or_404(Module, pk=module_id)
        assessment = Assessment.objects.create(
            module=module,
            title=title,
            description=description,
            assessment_type=assessment_type,
            unlock_order=unlock_order,
            total_marks=total_marks,
            pass_percentage=pass_percentage,
            time_limit_minutes=time_limit_minutes,
            attempts_allowed=attempts_allowed,
            due_date=due_date,
            is_published=is_published,
        )
        messages.success(request, f"Assessment '{assessment.title}' created successfully.")
        return redirect("admin_panel:assessment_list")

    assessments = Assessment.objects.select_related("module", "module__course").annotate(
        questions_count=Count("questions", distinct=True),
        submissions_count=Count("submissions", distinct=True),
    ).order_by("-created_at")

    search = request.GET.get("q", "").strip()
    course_filter = request.GET.get("course", "").strip()
    type_filter = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search:
        assessments = assessments.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(module__title__icontains=search)
            | Q(module__course__title__icontains=search)
        )
    if course_filter:
        assessments = assessments.filter(module__course__slug=course_filter)
    if type_filter:
        assessments = assessments.filter(assessment_type=type_filter)
    if status_filter == "published":
        assessments = assessments.filter(is_published=True)
    elif status_filter == "draft":
        assessments = assessments.filter(is_published=False)

    total_count = Assessment.objects.count()
    quiz_count = Assessment.objects.filter(assessment_type=Assessment.AssessmentType.QUIZ).count()
    assignment_count = Assessment.objects.filter(assessment_type=Assessment.AssessmentType.ASSIGNMENT).count()
    published_count = Assessment.objects.filter(is_published=True).count()

    paginator = Paginator(assessments, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    courses = Course.objects.prefetch_related("modules").order_by("title")

    context = {
        "page_title": "Assessments",
        "assessments": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "quiz_count": quiz_count,
        "assignment_count": assignment_count,
        "published_count": published_count,
        "courses": courses,
        "type_choices": Assessment.AssessmentType.choices,
        "selected_course": course_filter,
        "selected_type": type_filter,
        "selected_status": status_filter,
        "search_query": search,
    }
    return render(request, "assessments/list.html", context)


@admin_required
@require_POST
def assessment_edit(request, assessment_id):
    """Edit assessment parameters."""
    assessment = get_object_or_404(Assessment, pk=assessment_id)
    module_id = request.POST.get("module")
    if module_id:
        assessment.module = get_object_or_404(Module, pk=module_id)
    assessment.title = request.POST.get("title", assessment.title).strip()
    assessment.description = request.POST.get("description", assessment.description).strip()
    assessment.assessment_type = request.POST.get("assessment_type", assessment.assessment_type)
    assessment.unlock_order = int(request.POST.get("unlock_order") or assessment.unlock_order)
    assessment.total_marks = int(request.POST.get("total_marks") or assessment.total_marks)
    assessment.pass_percentage = int(request.POST.get("pass_percentage") or assessment.pass_percentage)
    time_limit_raw = request.POST.get("time_limit_minutes")
    assessment.time_limit_minutes = int(time_limit_raw) if time_limit_raw else None
    assessment.attempts_allowed = int(request.POST.get("attempts_allowed") or assessment.attempts_allowed)
    assessment.is_published = request.POST.get("is_published") in ["true", "True", "on", "1"]
    assessment.save()
    messages.success(request, f"Assessment '{assessment.title}' updated successfully.")
    return redirect("admin_panel:assessment_list")


@admin_required
def assessment_toggle_publish(request, assessment_id):
    """Toggle published state of an assessment (supports POST, GET, and AJAX)."""
    assessment = get_object_or_404(Assessment, pk=assessment_id)
    assessment.is_published = not assessment.is_published
    assessment.save()
    status_str = "Published" if assessment.is_published else "Draft"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({
            "success": True,
            "is_published": assessment.is_published,
            "status_text": status_str,
            "message": f"Assessment '{assessment.title}' is now {status_str}."
        })
    messages.success(request, f"Assessment '{assessment.title}' status updated to {status_str}.")
    referer = request.META.get("HTTP_REFERER")
    if referer:
        return redirect(referer)
    return redirect("admin_panel:assessment_list")


@admin_required
def assessment_delete(request, assessment_id):
    """Delete an assessment."""
    assessment = get_object_or_404(Assessment, pk=assessment_id)
    title = assessment.title
    assessment.delete()
    messages.success(request, f"Assessment '{title}' deleted successfully.")
    return redirect("admin_panel:assessment_list")


@admin_required
@require_http_methods(["GET", "POST"])
def assessment_questions(request):
    """Manage questions for a selected assessment."""
    assessment_id = request.GET.get("assessment") or request.POST.get("assessment_id")
    assessments = Assessment.objects.select_related("module", "module__course").order_by("-created_at")

    selected_assessment = None
    if assessment_id:
        selected_assessment = get_object_or_404(Assessment, pk=assessment_id)
    elif assessments.exists():
        selected_assessment = assessments.first()

    questions = []
    if selected_assessment:
        questions = selected_assessment.questions.all().order_by("order", "pk")

    context = {
        "page_title": "Question Builder",
        "assessments": assessments,
        "selected_assessment": selected_assessment,
        "questions": questions,
        "question_type_choices": Question.QuestionType.choices,
    }
    return render(request, "assessments/questions.html", context)


@admin_required
@require_POST
def question_save(request):
    """Save or update question with choices / correct answer."""
    assessment_id = request.POST.get("assessment_id")
    assessment = get_object_or_404(Assessment, pk=assessment_id)

    question_id = request.POST.get("question_id")
    question_text = request.POST.get("question_text", "").strip()
    question_type = request.POST.get("question_type", Question.QuestionType.MCQ)
    marks = int(request.POST.get("marks") or 1)
    explanation = request.POST.get("explanation", "").strip()
    order = int(request.POST.get("order") or (assessment.questions.count() + 1))
    correct_answer = request.POST.get("correct_answer", "").strip()

    options_raw = request.POST.get("options")
    options = []
    if options_raw:
        try:
            options = json.loads(options_raw) if isinstance(options_raw, str) else options_raw
        except Exception:
            options = [opt.strip() for opt in options_raw.split("\n") if opt.strip()]
    else:
        i = 0
        while f"option_{i}" in request.POST:
            val = request.POST.get(f"option_{i}").strip()
            if val:
                options.append(val)
            i += 1

    if question_id:
        q = get_object_or_404(Question, pk=question_id, assessment=assessment)
        q.question_text = question_text
        q.question_type = question_type
        q.marks = marks
        q.explanation = explanation
        q.order = order
        q.options = options
        q.correct_answer = correct_answer
        q.save()
        messages.success(request, f"Question #{q.order} updated successfully.")
    else:
        q = Question.objects.create(
            assessment=assessment,
            question_text=question_text,
            question_type=question_type,
            marks=marks,
            explanation=explanation,
            order=order,
            options=options,
            correct_answer=correct_answer,
        )
        messages.success(request, f"Question added to '{assessment.title}'.")

    # Update total marks on assessment
    total_q_marks = assessment.questions.aggregate(total=Sum("marks"))["total"] or 0
    if total_q_marks > 0 and assessment.total_marks != total_q_marks:
        assessment.total_marks = total_q_marks
        assessment.save(update_fields=["total_marks"])

    return redirect(f"{reverse('admin_panel:assessment_questions')}?assessment={assessment.pk}")


@admin_required
@require_POST
def question_delete(request, question_id):
    """Delete a question."""
    q = get_object_or_404(Question, pk=question_id)
    assessment_id = q.assessment_id
    q.delete()
    messages.success(request, "Question deleted successfully.")
    return redirect(f"{reverse('admin_panel:assessment_questions')}?assessment={assessment_id}")


@admin_required
@require_http_methods(["GET"])
def assessment_submissions(request):
    """View and filter student submissions."""
    submissions = Submission.objects.select_related(
        "assessment", "student", "graded_by", "assessment__module", "assessment__module__course"
    ).order_by("-submitted_at")

    assess_filter = request.GET.get("assessment", "").strip()
    status_filter = request.GET.get("status", "").strip()
    search = request.GET.get("q", "").strip()

    if search:
        submissions = submissions.filter(
            Q(student__username__icontains=search)
            | Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
            | Q(student__email__icontains=search)
            | Q(assessment__title__icontains=search)
        )
    if assess_filter:
        submissions = submissions.filter(assessment_id=assess_filter)
    if status_filter:
        submissions = submissions.filter(status=status_filter)

    total_count = Submission.objects.count()
    submitted_count = Submission.objects.filter(status=Submission.Status.SUBMITTED).count()
    graded_count = Submission.objects.filter(status=Submission.Status.GRADED).count()

    paginator = Paginator(submissions, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    assessments = Assessment.objects.order_by("title")

    context = {
        "page_title": "Submissions",
        "submissions": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "submitted_count": submitted_count,
        "graded_count": graded_count,
        "assessments": assessments,
        "status_choices": Submission.Status.choices,
        "selected_assessment": assess_filter,
        "selected_status": status_filter,
        "search_query": search,
    }
    return render(request, "assessments/submissions.html", context)


@admin_required
@require_POST
def submission_grade(request, submission_id):
    """Grade or return a student submission."""
    submission = get_object_or_404(Submission, pk=submission_id)
    score_val = request.POST.get("score")
    status_val = request.POST.get("status", Submission.Status.GRADED)

    if score_val is not None and score_val != "":
        submission.score = Decimal(str(score_val))
    submission.status = status_val
    submission.graded_by = request.user
    submission.graded_at = timezone.now()
    submission.save()

    messages.success(request, f"Submission #{submission.pk} graded successfully (Score: {submission.score}).")
    return redirect("admin_panel:assessment_submissions")


# DOUBTS
@admin_required
@require_GET
def doubt_list(request):
    """List doubt threads with status filters and instructors."""
    threads = DoubtThread.objects.select_related(
        "student", "lesson", "lesson__module", "lesson__module__course", "assigned_instructor"
    ).prefetch_related("messages").order_by("-updated_at")

    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    course_filter = request.GET.get("course", "").strip()

    if search:
        threads = threads.filter(
            Q(subject__icontains=search)
            | Q(student__username__icontains=search)
            | Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
            | Q(lesson__title__icontains=search)
        )
    if status_filter:
        threads = threads.filter(status=status_filter)
    if course_filter:
        threads = threads.filter(lesson__module__course_id=course_filter)

    total_count = DoubtThread.objects.count()
    open_count = DoubtThread.objects.filter(
        status__in=[DoubtThread.Status.OPEN, DoubtThread.Status.ASSIGNED, DoubtThread.Status.IN_PROGRESS, DoubtThread.Status.REOPENED]
    ).count()
    answered_count = DoubtThread.objects.filter(status=DoubtThread.Status.ANSWERED).count()
    resolved_count = DoubtThread.objects.filter(status=DoubtThread.Status.RESOLVED).count()

    paginator = Paginator(threads, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    courses = Course.objects.order_by("title")

    context = {
        "page_title": "Doubt Clearance",
        "threads": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "open_count": open_count,
        "answered_count": answered_count,
        "resolved_count": resolved_count,
        "courses": courses,
        "status_choices": DoubtThread.Status.choices,
        "selected_status": status_filter,
        "selected_course": course_filter,
        "search_query": search,
    }
    return render(request, "doubts/list.html", context)


@admin_required
@require_GET
def doubt_detail_admin(request, thread_id):
    """View full thread and messages history for admin / instructor."""
    thread = get_object_or_404(
        DoubtThread.objects.select_related(
            "student", "lesson", "lesson__module", "lesson__module__course", "assigned_instructor"
        ),
        pk=thread_id
    )
    messages_list = thread.messages.select_related("sender").order_by("created_at")
    instructors = User.objects.filter(role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN], is_active=True).order_by("first_name", "username")

    context = {
        "page_title": f"Doubt #{thread.pk}",
        "thread": thread,
        "messages_list": messages_list,
        "instructors": instructors,
        "status_choices": DoubtThread.Status.choices,
    }
    return render(request, "doubts/detail.html", context)


@admin_required
@require_POST
def doubt_reply_admin(request, thread_id):
    """Post an instructor reply to the thread."""
    thread = get_object_or_404(DoubtThread, pk=thread_id)
    message_text = request.POST.get("message", "").strip()
    attachment = request.FILES.get("attachment")
    mark_resolved = request.POST.get("mark_resolved") in ["true", "True", "on", "1"]

    if message_text or attachment:
        DoubtMessage.objects.create(
            thread=thread,
            sender=request.user,
            message=message_text,
            attachment=attachment,
        )

        if mark_resolved:
            thread.status = DoubtThread.Status.RESOLVED
        else:
            thread.status = DoubtThread.Status.ANSWERED

        if not thread.assigned_instructor:
            thread.assigned_instructor = request.user
        thread.save()
        messages.success(request, "Reply posted to student successfully.")

    return redirect("admin_panel:doubt_detail_admin", thread_id=thread.pk)


@admin_required
@require_POST
def doubt_status_admin(request, thread_id):
    """Update doubt thread status and assigned instructor."""
    thread = get_object_or_404(DoubtThread, pk=thread_id)
    status_val = request.POST.get("status")
    assigned_id = request.POST.get("assigned_instructor")

    if status_val in dict(DoubtThread.Status.choices):
        thread.status = status_val
    if assigned_id:
        mentor = User.objects.filter(pk=assigned_id, role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN]).first()
        thread.assigned_instructor = mentor
    elif "assigned_instructor" in request.POST:
        thread.assigned_instructor = None

    thread.save()
    messages.success(request, f"Doubt thread #{thread.pk} updated.")
    return redirect("admin_panel:doubt_detail_admin", thread_id=thread.pk)


# CONSULTATIONS
@admin_required
@require_GET
def consultation_list(request):
    """List career consultation bookings with status/search filters and summary metrics."""
    bookings = ConsultationBooking.objects.select_related("assigned_to").order_by("-created_at")

    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search:
        bookings = bookings.filter(
            Q(name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
            | Q(message__icontains=search)
        )

    if status_filter:
        bookings = bookings.filter(status=status_filter)

    total_count = ConsultationBooking.objects.count()
    new_count = ConsultationBooking.objects.filter(status=ConsultationBooking.Status.NEW).count()
    contacted_count = ConsultationBooking.objects.filter(status=ConsultationBooking.Status.CONTACTED).count()
    scheduled_count = ConsultationBooking.objects.filter(status=ConsultationBooking.Status.SCHEDULED).count()
    completed_count = ConsultationBooking.objects.filter(status=ConsultationBooking.Status.COMPLETED).count()

    paginator = Paginator(bookings, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    instructors = User.objects.filter(role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN], is_active=True).order_by("first_name", "username")

    context = {
        "page_title": "Career Consultations",
        "page_obj": page_obj,
        "bookings": page_obj,
        "total_count": total_count,
        "new_count": new_count,
        "contacted_count": contacted_count,
        "scheduled_count": scheduled_count,
        "completed_count": completed_count,
        "instructors": instructors,
        "status_choices": ConsultationBooking.Status.choices,
        "selected_status": status_filter,
        "search_query": search,
    }
    return render(request, "consultations/list.html", context)


@admin_required
@require_POST
def consultation_update(request, booking_id):
    """Update consultation booking status, assigned mentor, and internal notes."""
    booking = get_object_or_404(ConsultationBooking, pk=booking_id)
    new_status = request.POST.get("status", "").strip()
    assigned_to_id = request.POST.get("assigned_to", "").strip()
    internal_notes = request.POST.get("internal_notes", "").strip()

    if new_status in dict(ConsultationBooking.Status.choices):
        booking.status = new_status

    if assigned_to_id:
        mentor = User.objects.filter(pk=assigned_to_id, role__in=[User.Role.INSTRUCTOR, User.Role.ADMIN]).first()
        booking.assigned_to = mentor
    elif "assigned_to" in request.POST:
        booking.assigned_to = None

    if "internal_notes" in request.POST:
        booking.internal_notes = internal_notes

    booking.save()
    messages.success(request, f"Consultation booking #{booking.pk} for {booking.name} updated successfully.")
    return redirect("admin_panel:consultation_list")
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


# NOTIFICATION 

@login_required
@require_GET

def notification_api_list(request):
    """API endpoint returning the admin user's latest notifications and unread count."""
    notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")[:10]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

    data = {
        "unread_count": unread_count,
        "notifications": [
            {
                "id": n.pk,
                "title": n.title,
                "message":n.message,
                "type": n.get_notification_type_display(),
                "is_read": n.is_read,
                "created_at": timezone.localtime(n.created_at).strftime("%b %d, %Y, %H:%M"),
            }
            for n in notifications
        ]
    }
    return JsonResponse(data)



@login_required
@require_GET
def notification_list(request):
    """Render notification list for the logged-in user."""
    notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")
    return render(request, "notifications/list.html", {"notifications": notifications})


@login_required
@require_POST
def notification_mark_read_api(request, notification_id):
    """Mark a specific notification as read."""
    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return JsonResponse({"success":True})

@login_required
@require_POST
def notification_mark_all_read_api(request):
    """Mark all notifications for the current user as read when opening the modal."""
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"success": True})

@admin_required
@require_POST
def mark_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"status": "success"})
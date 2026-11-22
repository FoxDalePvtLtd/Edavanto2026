from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from admin_panel.permissions import admin_required
from core.center_services import (
    approve_center_application,
    create_center_by_admin,
    ensure_default_subscription_plans,
    record_manual_subscription_activation,
    reject_center_application,
    toggle_center_suspension,
)
from core.models import (
    AuditLog,
    Center,
    CenterApplication,
    CenterInstructor,
    CenterSubscription,
    CenterSubscriptionPayment,
    CenterSubscriptionPlan,
    Course,
    CourseApprovalHistory,
    Enrollment,
    Notification,
    NotificationDelivery,
    User,
)


# ============================================================
# CENTER OVERVIEW DASHBOARD
# ============================================================

@admin_required
@require_GET
def center_overview(request):
    """
    Overview page for administrator center management.
    """
    ensure_default_subscription_plans()
    now = timezone.now()

    total_centers = Center.objects.count()
    approved_centers = Center.objects.filter(is_active=True, is_suspended=False).count()
    suspended_centers = Center.objects.filter(is_suspended=True).count()

    pending_applications = CenterApplication.objects.filter(status=CenterApplication.Status.PENDING).count()
    rejected_applications = CenterApplication.objects.filter(status=CenterApplication.Status.REJECTED).count()

    active_subscriptions = CenterSubscription.objects.filter(
        status=CenterSubscription.Status.ACTIVE,
        end_date__gt=now,
    ).count()

    expired_subscriptions = CenterSubscription.objects.filter(
        Q(status=CenterSubscription.Status.EXPIRED) |
        Q(status=CenterSubscription.Status.ACTIVE, end_date__lte=now)
    ).count()

    pending_course_approvals = Course.objects.filter(
        center__isnull=False,
        approval_status=Course.ApprovalStatus.PENDING,
    ).count()

    recent_applications = CenterApplication.objects.all().order_by("-created_at")[:6]
    recent_centers = Center.objects.select_related("owner").all().order_by("-created_at")[:6]

    context = {
        "total_centers": total_centers,
        "approved_centers": approved_centers,
        "suspended_centers": suspended_centers,
        "pending_applications": pending_applications,
        "rejected_applications": rejected_applications,
        "active_subscriptions": active_subscriptions,
        "expired_subscriptions": expired_subscriptions,
        "pending_course_approvals": pending_course_approvals,
        "recent_applications": recent_applications,
        "recent_centers": recent_centers,
        "page_title": "Centers Overview",
    }
    return render(request, "centers/overview.html", context)


# ============================================================
# CENTER APPLICATIONS
# ============================================================

@admin_required
@require_GET
def center_applications(request):
    """
    List and filter center applications.
    """
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()

    qs = CenterApplication.objects.all().order_by("-created_at")

    if status_filter:
        qs = qs.filter(status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(center_name__icontains=search_query) |
            Q(official_email__icontains=search_query) |
            Q(owner_name__icontains=search_query) |
            Q(owner_email__icontains=search_query) |
            Q(city__icontains=search_query)
        )

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "applications": page_obj.object_list,
        "page_obj": page_obj,
        "status_filter": status_filter,
        "search_query": search_query,
        "status_choices": CenterApplication.Status.choices,
        "page_title": "Center Applications",
    }
    return render(request, "centers/applications_list.html", context)


@admin_required
@require_GET
def center_application_detail(request, app_id):
    """
    Inspect an individual center registration application.
    """
    application = get_object_or_404(CenterApplication, pk=app_id)
    return render(
        request,
        "centers/application_detail.html",
        {"application": application, "page_title": f"Application: {application.center_name}"},
    )


@admin_required
@require_POST
def center_application_approve(request, app_id):
    """
    Approve application, create/activate Center & owner, and send notification.
    """
    application = get_object_or_404(CenterApplication, pk=app_id)
    admin_notes = request.POST.get("admin_notes", "").strip()

    center = approve_center_application(application, reviewer=request.user, admin_notes=admin_notes)
    messages.success(request, f"Center '{center.name}' approved successfully! Owner account has been linked.")
    return redirect("admin_panel:center_detail", center_id=center.id)


@admin_required
@require_POST
def center_application_reject(request, app_id):
    """
    Reject application with required reason.
    """
    application = get_object_or_404(CenterApplication, pk=app_id)
    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(request, "A reason must be provided when rejecting an application.")
        return redirect("admin_panel:center_application_detail", app_id=app_id)

    reject_center_application(application, reviewer=request.user, reason=reason)
    messages.warning(request, f"Application for '{application.center_name}' rejected.")
    return redirect("admin_panel:center_applications")


# ============================================================
# CENTER MANAGEMENT (CRUD)
# ============================================================

@admin_required
@require_GET
def center_list(request):
    """
    Directory of all created centers.
    """
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    qs = (
        Center.objects
        .select_related("owner")
        .prefetch_related("subscriptions", "instructors", "courses")
        .order_by("-created_at")
    )

    if status_filter == "suspended":
        qs = qs.filter(is_suspended=True)
    elif status_filter == "active":
        qs = qs.filter(is_active=True, is_suspended=False)

    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(owner__username__icontains=search_query)
        )

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "centers": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "page_title": "All Centers",
    }
    return render(request, "centers/center_list.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def center_create(request):
    """
    Manually create a Center and associated owner account.
    """
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        contact_number = request.POST.get("contact_number", "").strip()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        postal_code = request.POST.get("postal_code", "").strip()
        website = request.POST.get("website", "").strip()
        description = request.POST.get("description", "").strip()

        owner_name = request.POST.get("owner_name", "").strip()
        owner_email = request.POST.get("owner_email", "").strip()
        owner_phone = request.POST.get("owner_phone", "").strip()
        owner_password = request.POST.get("owner_password", "").strip()

        errors = {}
        if not name:
            errors["name"] = "Center name is required."
        if not email:
            errors["email"] = "Center official email is required."
        elif Center.objects.filter(email=email).exists():
            errors["email"] = "Center with this email already exists."

        if not owner_email:
            errors["owner_email"] = "Owner login email is required."

        if errors:
            return render(
                request,
                "centers/center_form.html",
                {"errors": errors, "form_data": request.POST, "page_title": "Add New Center"},
                status=400,
            )

        center = create_center_by_admin(
            name=name,
            email=email,
            contact_number=contact_number,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
            website=website,
            description=description,
            owner_name=owner_name,
            owner_email=owner_email,
            owner_phone=owner_phone,
            owner_password=owner_password,
            creator=request.user,
        )

        messages.success(request, f"Center '{center.name}' created successfully!")
        return redirect("admin_panel:center_detail", center_id=center.id)

    return render(
        request,
        "centers/center_form.html",
        {"form_data": {}, "errors": {}, "page_title": "Add New Center"},
    )


@admin_required
@require_GET
def center_detail(request, center_id):
    """
    Complete inspection of a Center: details, owner, instructors, courses, enrollments, subscriptions.
    """
    center = get_object_or_404(
        Center.objects.select_related("owner").prefetch_related("instructors__instructor", "courses"),
        pk=center_id,
    )

    instructors = center.instructors.select_related("instructor").filter(is_active=True)
    courses = center.courses.all().order_by("-created_at")

    # Enrolled students across center courses
    enrollments = (
        Enrollment.objects
        .filter(course__center=center)
        .select_related("student", "course")
        .order_by("-enrolled_at")[:15]
    )

    # Subscriptions and payments
    subscriptions = center.subscriptions.select_related("plan").all().order_by("-created_at")
    active_subscription = center.get_active_subscription()

    payments = (
        CenterSubscriptionPayment.objects
        .filter(subscription__center=center)
        .select_related("subscription__plan")
        .order_by("-created_at")
    )

    # Available plans for manual activation
    plans = CenterSubscriptionPlan.objects.filter(is_active=True)

    context = {
        "center": center,
        "instructors": instructors,
        "courses": courses,
        "enrollments": enrollments,
        "subscriptions": subscriptions,
        "active_subscription": active_subscription,
        "payments": payments,
        "plans": plans,
        "page_title": f"Center: {center.name}",
    }
    return render(request, "centers/center_detail.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def center_edit(request, center_id):
    """
    Edit existing center information.
    """
    center = get_object_or_404(Center.objects.select_related("owner"), pk=center_id)

    if request.method == "POST":
        center.name = request.POST.get("name", "").strip() or center.name
        center.contact_number = request.POST.get("contact_number", "").strip()
        center.address = request.POST.get("address", "").strip()
        center.city = request.POST.get("city", "").strip()
        center.state = request.POST.get("state", "").strip()
        center.postal_code = request.POST.get("postal_code", "").strip()
        center.website = request.POST.get("website", "").strip()
        center.description = request.POST.get("description", "").strip()
        center.is_active = request.POST.get("is_active") == "on"
        center.save()

        messages.success(request, f"Center '{center.name}' updated successfully.")
        return redirect("admin_panel:center_detail", center_id=center.id)

    return render(
        request,
        "centers/center_form.html",
        {"center": center, "form_data": center, "page_title": f"Edit {center.name}"},
    )


@admin_required
@require_POST
def center_toggle_suspend(request, center_id):
    """
    Suspend or unsuspend a center.
    """
    center = get_object_or_404(Center, pk=center_id)
    reason = request.POST.get("reason", "").strip()

    toggle_center_suspension(center, actor=request.user, reason=reason)
    status_str = "suspended" if center.is_suspended else "unsuspended"
    messages.info(request, f"Center '{center.name}' has been {status_str}.")
    return redirect("admin_panel:center_detail", center_id=center.id)


@admin_required
@require_POST
def center_manual_subscription_activate(request, center_id):
    """
    Manually activate or renew a subscription for offline payment.
    """
    center = get_object_or_404(Center, pk=center_id)
    plan_id = request.POST.get("plan_id")
    notes = request.POST.get("notes", "").strip()

    plan = get_object_or_404(CenterSubscriptionPlan, pk=plan_id, is_active=True)

    subscription, payment = record_manual_subscription_activation(
        center=center,
        plan=plan,
        actor=request.user,
        notes=notes,
    )

    messages.success(
        request,
        f"Subscription '{plan.name}' activated for {center.name} until {subscription.end_date:%d %B %Y}.",
    )
    return redirect("admin_panel:center_detail", center_id=center.id)


# ============================================================
# SUBSCRIPTION PLANS MANAGEMENT
# ============================================================

@admin_required
@require_GET
def center_subscription_plans(request):
    """
    List and manage configurable subscription plans.
    """
    ensure_default_subscription_plans()
    plans = CenterSubscriptionPlan.objects.all().order_by("duration_months", "price")
    return render(
        request,
        "centers/subscription_plans.html",
        {"plans": plans, "page_title": "Subscription Plans"},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def center_subscription_plan_edit(request, plan_id):
    """
    Edit price, description, and status of a subscription plan.
    """
    plan = get_object_or_404(CenterSubscriptionPlan, pk=plan_id)

    if request.method == "POST":
        price = request.POST.get("price", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        try:
            plan.price = Decimal(price)
            if plan.price < 0:
                raise ValueError("Price cannot be negative.")
        except Exception:
            messages.error(request, "Please enter a valid price.")
            return render(request, "centers/plan_form.html", {"plan": plan, "page_title": f"Edit {plan.name}"})

        plan.description = description
        plan.is_active = is_active
        plan.save()

        messages.success(request, f"Plan '{plan.name}' updated successfully.")
        return redirect("admin_panel:center_subscription_plans")

    return render(
        request,
        "centers/plan_form.html",
        {"plan": plan, "page_title": f"Edit {plan.name}"},
    )


# ============================================================
# CENTER COURSE APPROVALS
# ============================================================

@admin_required
@require_GET
def center_course_approvals(request):
    """
    List all center courses awaiting or subjected to administrative approval.
    """
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()

    qs = (
        Course.objects
        .filter(center__isnull=False)
        .select_related("center", "instructor", "approved_by")
        .prefetch_related("modules")
        .order_by("-updated_at")
    )

    if status_filter:
        qs = qs.filter(approval_status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) |
            Q(center__name__icontains=search_query) |
            Q(instructor__username__icontains=search_query)
        )

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "courses": page_obj.object_list,
        "page_obj": page_obj,
        "status_filter": status_filter,
        "search_query": search_query,
        "approval_choices": Course.ApprovalStatus.choices,
        "page_title": "Center Course Approvals",
    }
    return render(request, "centers/course_approvals.html", context)


@admin_required
@require_http_methods(["GET", "POST"])
def center_course_review(request, course_id):
    """
    Inspect course syllabus/modules/lessons and approve, reject, or request changes.
    """
    course = get_object_or_404(
        Course.objects.select_related("center", "instructor").prefetch_related(
            "modules__lessons__materials",
            "modules__lessons__video_asset",
            "approval_history__reviewer",
        ),
        pk=course_id,
        center__isnull=False,
    )

    if request.method == "POST":
        decision = request.POST.get("decision", "").strip()
        feedback = request.POST.get("feedback", "").strip()

        if decision not in ("approved", "rejected", "changes_requested"):
            messages.error(request, "Invalid decision selected.")
            return redirect("admin_panel:center_course_review", course_id=course.id)

        if decision in ("rejected", "changes_requested") and not feedback:
            messages.error(request, "Feedback explanation is required when rejecting or requesting changes.")
            return redirect("admin_panel:center_course_review", course_id=course.id)

        now = timezone.now()
        course.approval_status = (
            Course.ApprovalStatus.APPROVED if decision == "approved"
            else Course.ApprovalStatus.REJECTED if decision == "rejected"
            else Course.ApprovalStatus.CHANGES_REQUESTED
        )
        course.approval_feedback = feedback
        course.approved_by = request.user
        course.approved_at = now
        course.save(update_fields=["approval_status", "approval_feedback", "approved_by", "approved_at", "updated_at"])

        # Record History
        CourseApprovalHistory.objects.create(
            course=course,
            reviewer=request.user,
            decision=course.approval_status,
            feedback=feedback,
        )

        # Notify Center Owner
        if course.center and course.center.owner:
            decision_label = (
                "Approved" if decision == "approved"
                else "Rejected" if decision == "rejected"
                else "Changes Requested"
            )
            msg = (
                f"Your course '{course.title}' has been {decision_label} by the administrator."
                + (f" Notes: {feedback}" if feedback else "")
            )
            notif = Notification.objects.create(
                recipient=course.center.owner,
                title=f"Course Review: {decision_label}",
                message=msg,
                notification_type=Notification.NotificationType.COURSE,
            )
            NotificationDelivery.objects.create(
                notification=notif,
                channel=NotificationDelivery.Channel.IN_APP,
                status=NotificationDelivery.Status.SENT,
                sent_at=now,
            )

        messages.success(request, f"Course '{course.title}' review recorded: {decision_label}.")
        return redirect("admin_panel:center_course_approvals")

    modules = course.modules.all().order_by("order", "pk")
    history = course.approval_history.all()

    context = {
        "course": course,
        "modules": modules,
        "history": history,
        "page_title": f"Review Course: {course.title}",
    }
    return render(request, "centers/course_review.html", context)

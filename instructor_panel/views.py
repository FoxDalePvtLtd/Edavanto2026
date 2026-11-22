from django.contrib import messages
from django.db import models, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import (
    Assessment,
    Attendance,
    Batch,
    BatchSession,
    Course,
    DoubtMessage,
    DoubtThread,
    Enrollment,
    Lesson,
    Notification,
    Submission,
)
from instructor_panel.forms import (
    DoubtReplyForm,
    InstructorProfileForm,
    SubmissionGradeForm,
)
from instructor_panel.permissions import instructor_required


@instructor_required
def dashboard(request):
    """
    Instructor Overview Dashboard.
    Displays metrics for assigned courses, students, doubts, upcoming sessions, and assessments.
    """
    user = request.user

    assigned_courses = Course.objects.filter(instructor=user)
    courses_count = assigned_courses.count()

    total_students = (
        Enrollment.objects.filter(
            course__instructor=user,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.APPROVED,
        )
        .values("student")
        .distinct()
        .count()
    )

    doubt_qs = DoubtThread.objects.filter(
        Q(assigned_instructor=user) | Q(lesson__module__course__instructor=user)
    )
    pending_doubts_count = doubt_qs.filter(
        status__in=[DoubtThread.Status.OPEN, DoubtThread.Status.ASSIGNED]
    ).count()

    pending_submissions_count = Submission.objects.filter(
        assessment__lesson__module__course__instructor=user,
        status=Submission.Status.SUBMITTED,
    ).count()

    upcoming_sessions = (
        BatchSession.objects.filter(
            Q(instructor=user) | Q(batch__instructor=user),
            date__gte=timezone.now().date(),
        )
        .select_related("batch", "batch__course")
        .order_by("date", "start_time")[:5]
    )

    recent_doubts = (
        doubt_qs.select_related("student", "lesson", "lesson__module__course")
        .order_by("-updated_at")[:6]
    )

    context = {
        "courses_count": courses_count,
        "total_students": total_students,
        "pending_doubts_count": pending_doubts_count,
        "pending_submissions_count": pending_submissions_count,
        "upcoming_sessions": upcoming_sessions,
        "recent_doubts": recent_doubts,
        "assigned_courses": assigned_courses[:4],
        "active_nav": "dashboard",
    }
    return render(request, "instructor_panel/dashboard.html", context)


@instructor_required
def course_list(request):
    """
    List of courses assigned to the authenticated instructor.
    """
    courses = (
        Course.objects.filter(instructor=request.user)
        .annotate(
            enrolled_count=Count("enrollments", filter=Q(enrollments__payment_status=Enrollment.PaymentStatus.PAID)),
            modules_count=Count("modules", distinct=True),
        )
        .select_related("center")
        .order_by("-created_at")
    )

    query = request.GET.get("q", "").strip()
    if query:
        courses = courses.filter(title__icontains=query)

    context = {
        "courses": courses,
        "query": query,
        "active_nav": "courses",
    }
    return render(request, "instructor_panel/course_list.html", context)


@instructor_required
def course_lessons(request, course_id):
    """
    Detailed curriculum / syllabus and learning content for an assigned course.
    """
    course = get_object_or_404(Course, id=course_id, instructor=request.user)
    modules = (
        course.modules.prefetch_related(
            "lessons",
            "lessons__resources",
            "lessons__assessments",
        )
        .order_by("order", "id")
    )

    context = {
        "course": course,
        "modules": modules,
        "active_nav": "courses",
    }
    return render(request, "instructor_panel/course_lessons.html", context)


@instructor_required
def doubt_list(request):
    """
    List of student doubts assigned to or relevant to this instructor's courses.
    """
    status_filter = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()

    doubts = (
        DoubtThread.objects.filter(
            Q(assigned_instructor=request.user)
            | Q(lesson__module__course__instructor=request.user)
        )
        .select_related("student", "lesson", "lesson__module__course")
        .order_by("-updated_at")
    )

    if status_filter and status_filter in DoubtThread.Status.values:
        doubts = doubts.filter(status=status_filter)

    if query:
        doubts = doubts.filter(
            Q(subject__icontains=query)
            | Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__email__icontains=query)
            | Q(lesson__title__icontains=query)
        )

    context = {
        "doubts": doubts,
        "status_filter": status_filter,
        "query": query,
        "status_choices": DoubtThread.Status.choices,
        "active_nav": "doubts",
    }
    return render(request, "instructor_panel/doubt_list.html", context)


@instructor_required
def doubt_detail(request, thread_id):
    """
    View doubt thread and post replies.
    """
    thread = get_object_or_404(
        DoubtThread.objects.select_related("student", "lesson", "lesson__module__course"),
        Q(assigned_instructor=request.user)
        | Q(lesson__module__course__instructor=request.user),
        id=thread_id,
    )

    messages_list = thread.messages.select_related("sender").order_by("created_at")

    if request.method == "POST":
        form = DoubtReplyForm(request.POST, request.FILES)
        if form.is_valid():
            reply = form.save(commit=False)
            reply.thread = thread
            reply.sender = request.user
            reply.save()

            # Update thread status to ANSWERED if currently OPEN or ASSIGNED
            if thread.status in [DoubtThread.Status.OPEN, DoubtThread.Status.ASSIGNED]:
                thread.status = DoubtThread.Status.ANSWERED
                thread.save(update_fields=["status", "updated_at"])

            # Notify the student
            instructor_name = request.user.get_full_name() or request.user.username
            Notification.objects.create(
                recipient=thread.student,
                title="New Instructor Reply on Your Doubt",
                message=f"Instructor {instructor_name} replied to your doubt on '{thread.subject}'.",
                notification_type=Notification.NotificationType.DOUBT,
            )

            messages.success(request, "Your reply has been posted successfully.")
            return redirect("instructor_panel:doubt_detail", thread_id=thread.id)
    else:
        form = DoubtReplyForm()

    context = {
        "thread": thread,
        "messages_list": messages_list,
        "form": form,
        "active_nav": "doubts",
    }
    return render(request, "instructor_panel/doubt_detail.html", context)


@instructor_required
def doubt_resolve(request, thread_id):
    """
    Mark doubt thread as RESOLVED.
    """
    thread = get_object_or_404(
        DoubtThread,
        Q(assigned_instructor=request.user)
        | Q(lesson__module__course__instructor=request.user),
        id=thread_id,
    )

    if request.method == "POST":
        thread.status = DoubtThread.Status.RESOLVED
        thread.save(update_fields=["status", "updated_at"])

        Notification.objects.create(
            recipient=thread.student,
            title="Doubt Resolved",
            message=f"Your doubt on '{thread.subject}' has been marked as resolved by your instructor.",
            notification_type=Notification.NotificationType.DOUBT,
        )

        messages.success(request, f"Doubt #{thread.id} marked as resolved.")
    return redirect("instructor_panel:doubt_detail", thread_id=thread.id)


@instructor_required
def assessment_list(request):
    """
    List of assessments belonging to courses assigned to this instructor.
    """
    assessments = (
        Assessment.objects.filter(lesson__module__course__instructor=request.user)
        .annotate(
            submissions_count=Count("submissions"),
            pending_count=Count(
                "submissions",
                filter=Q(submissions__status=Submission.Status.SUBMITTED),
            ),
        )
        .select_related("lesson", "lesson__module", "lesson__module__course")
        .order_by("-created_at")
    )

    query = request.GET.get("q", "").strip()
    if query:
        assessments = assessments.filter(
            Q(title__icontains=query) | Q(lesson__module__course__title__icontains=query)
        )

    context = {
        "assessments": assessments,
        "query": query,
        "active_nav": "assessments",
    }
    return render(request, "instructor_panel/assessment_list.html", context)


@instructor_required
def assessment_submissions(request, assessment_id):
    """
    View all student submissions for a specific assessment.
    """
    assessment = get_object_or_404(
        Assessment.objects.select_related("lesson", "lesson__module", "lesson__module__course"),
        id=assessment_id,
        lesson__module__course__instructor=request.user,
    )

    submissions = (
        Submission.objects.filter(assessment=assessment)
        .select_related("student", "graded_by")
        .order_by("-submitted_at")
    )

    context = {
        "assessment": assessment,
        "submissions": submissions,
        "active_nav": "assessments",
    }
    return render(request, "instructor_panel/assessment_submissions.html", context)


@instructor_required
def submission_grade(request, submission_id):
    """
    Grade or review an individual student submission.
    """
    submission = get_object_or_404(
        Submission.objects.select_related(
            "assessment", "student", "assessment__lesson__module__course"
        ),
        id=submission_id,
        assessment__lesson__module__course__instructor=request.user,
    )

    max_marks = float(submission.assessment.total_marks or 100)

    if request.method == "POST":
        form = SubmissionGradeForm(request.POST, instance=submission, max_score=max_marks)
        if form.is_valid():
            graded_submission = form.save(commit=False)
            graded_submission.graded_by = request.user
            graded_submission.graded_at = timezone.now()
            graded_submission.save()

            Notification.objects.create(
                recipient=submission.student,
                title="Assessment Graded",
                message=(
                    f"Your submission for '{submission.assessment.title}' has been evaluated. "
                    f"Score: {graded_submission.score}/{max_marks}."
                ),
                notification_type=Notification.NotificationType.GENERAL,
            )

            messages.success(request, f"Submission for {submission.student.get_full_name() or submission.student.username} graded successfully.")
            return redirect("instructor_panel:assessment_submissions", assessment_id=submission.assessment.id)
    else:
        form = SubmissionGradeForm(instance=submission, max_score=max_marks)

    context = {
        "submission": submission,
        "assessment": submission.assessment,
        "form": form,
        "max_marks": max_marks,
        "active_nav": "assessments",
    }
    return render(request, "instructor_panel/submission_grade.html", context)


@instructor_required
def batch_list(request):
    """
    List of batches assigned to this instructor.
    """
    batches = (
        Batch.objects.filter(instructor=request.user)
        .select_related("course", "center")
        .prefetch_related("sessions")
        .order_by("-start_date")
    )

    context = {
        "batches": batches,
        "active_nav": "batches",
    }
    return render(request, "instructor_panel/batch_list.html", context)


@instructor_required
def session_attendance(request, batch_id, session_id):
    """
    Mark and view attendance for a batch session.
    """
    batch = get_object_or_404(Batch, id=batch_id, instructor=request.user)
    session = get_object_or_404(BatchSession, id=session_id, batch=batch)

    # Students enrolled in this batch's course
    enrolled_students = (
        Enrollment.objects.filter(
            course=batch.course,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.APPROVED,
        )
        .select_related("student")
        .order_by("student__first_name", "student__last_name")
    )

    # Existing attendance records for this session
    attendance_records = {
        att.student_id: att
        for att in Attendance.objects.filter(session=session).select_related("student")
    }

    if request.method == "POST":
        with transaction.atomic():
            for enrollment in enrolled_students:
                student = enrollment.student
                status_key = f"status_{student.id}"
                remarks_key = f"remarks_{student.id}"

                status_val = request.POST.get(status_key)
                remarks_val = request.POST.get(remarks_key, "").strip()

                if status_val and status_val in Attendance.Status.values:
                    Attendance.objects.update_or_create(
                        session=session,
                        student=student,
                        defaults={
                            "status": status_val,
                            "remarks": remarks_val,
                            "marked_by": request.user,
                            "marked_at": timezone.now(),
                        },
                    )

            # Mark session completed if instructed
            if request.POST.get("mark_session_completed") == "1":
                session.status = BatchSession.Status.COMPLETED
                session.save(update_fields=["status"])

        messages.success(request, f"Attendance for session '{session.title}' saved successfully.")
        return redirect("instructor_panel:session_attendance", batch_id=batch.id, session_id=session.id)

    # Prepare student rows with existing attendance data
    student_rows = []
    for enrollment in enrolled_students:
        att = attendance_records.get(enrollment.student_id)
        student_rows.append({
            "student": enrollment.student,
            "attendance": att,
            "status": att.status if att else Attendance.Status.PRESENT,
            "remarks": att.remarks if att else "",
        })

    context = {
        "batch": batch,
        "session": session,
        "student_rows": student_rows,
        "attendance_statuses": Attendance.Status.choices,
        "active_nav": "batches",
    }
    return render(request, "instructor_panel/session_attendance.html", context)


@instructor_required
def student_progress(request):
    """
    View enrolled students across instructor's assigned courses and track their learning progress.
    """
    enrollments = (
        Enrollment.objects.filter(
            course__instructor=request.user,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.APPROVED,
        )
        .select_related("student", "course")
        .order_by("-enrolled_at")
    )

    course_id = request.GET.get("course")
    query = request.GET.get("q", "").strip()

    if course_id:
        enrollments = enrollments.filter(course_id=course_id)

    if query:
        enrollments = enrollments.filter(
            Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__email__icontains=query)
        )

    assigned_courses = Course.objects.filter(instructor=request.user)

    context = {
        "enrollments": enrollments,
        "assigned_courses": assigned_courses,
        "selected_course_id": int(course_id) if course_id and course_id.isdigit() else None,
        "query": query,
        "active_nav": "students",
    }
    return render(request, "instructor_panel/student_progress.html", context)


@instructor_required
def notifications(request):
    """
    View instructor notifications.
    """
    user_notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")

    if request.method == "POST" and request.POST.get("action") == "mark_all_read":
        user_notifications.filter(is_read=False).update(is_read=True)
        messages.success(request, "All notifications marked as read.")
        return redirect("instructor_panel:notifications")

    context = {
        "notifications": user_notifications,
        "active_nav": "notifications",
    }
    return render(request, "instructor_panel/notifications.html", context)


@instructor_required
def mark_notification_read(request, notification_id):
    """
    Mark single notification as read.
    """
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return redirect("instructor_panel:notifications")


@instructor_required
def profile(request):
    """
    Instructor profile view and update.
    """
    if request.method == "POST":
        form = InstructorProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("instructor_panel:profile")
    else:
        form = InstructorProfileForm(instance=request.user)

    context = {
        "form": form,
        "center_link": getattr(request, "center_link", None),
        "active_nav": "profile",
    }
    return render(request, "instructor_panel/profile.html", context)

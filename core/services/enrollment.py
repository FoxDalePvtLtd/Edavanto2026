from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import (
    Course,
    Enrollment,
    LearningProgress,
    Lesson,
)


# ============================================================
# ENROLLMENT ACCESS
# ============================================================

def get_student_enrollment(student, course):
    """
    Return the student's enrollment for a specific course.

    Returns:
        Enrollment | None
    """

    if not student or not student.is_authenticated:
        return None

    return (
        Enrollment.objects
        .select_related("course")
        .filter(
            student=student,
            course=course,
        )
        .first()
    )


def has_paid_access(enrollment):
    """
    Determine whether the enrollment has a valid payment state
    for learning access.

    Full payment:
        paid

    Installment payment:
        partially_paid

    Failed/refunded/pending:
        no access
    """

    if enrollment is None:
        return False

    return enrollment.payment_status in {
        Enrollment.PaymentStatus.PAID,
        Enrollment.PaymentStatus.PARTIALLY_PAID,
    }


def has_approval_access(enrollment):
    """
    Determine whether instructor/admin approval allows access.
    """

    if enrollment is None:
        return False

    return (
        enrollment.approval_status
        == Enrollment.ApprovalStatus.ACCEPTED
    )


def enrollment_has_access(enrollment):
    """
    Final server-side access decision.

    A student must have:

        1. Valid enrollment
        2. Valid payment status
        3. Accepted enrollment
        4. Access not paused
    """

    if enrollment is None:
        return False

    if enrollment.access_paused:
        return False

    if not has_paid_access(enrollment):
        return False

    if not has_approval_access(enrollment):
        return False

    return True


# ============================================================
# COURSE ENROLLMENT CREATION
# ============================================================

@transaction.atomic
def create_enrollment(student, course):
    """
    Create or retrieve an enrollment.

    This does NOT mark the student as paid.

    Payment processing must update payment_status separately.
    """

    if not student or not student.is_authenticated:
        raise ValueError("Authentication is required.")

    if student.role != student.Role.STUDENT:
        raise ValueError("Only students can enroll in courses.")

    if course.status != Course.Status.PUBLISHED:
        raise ValueError("This course is not currently available.")

    enrollment, created = (
        Enrollment.objects
        .select_for_update()
        .get_or_create(
            student=student,
            course=course,
            defaults={
                "payment_status": Enrollment.PaymentStatus.PENDING,
                "approval_status": (
                    Enrollment.ApprovalStatus.PENDING
                ),
            },
        )
    )

    return enrollment, created


# ============================================================
# PAYMENT / APPROVAL STATE
# ============================================================

@transaction.atomic
def mark_enrollment_payment_paid(enrollment):
    """
    Mark an enrollment as fully paid.

    For courses that do not require instructor approval,
    enrollment is automatically accepted.

    For courses that require approval,
    enrollment remains pending.
    """

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .select_related("course")
        .get(pk=enrollment.pk)
    )

    enrollment.payment_status = Enrollment.PaymentStatus.PAID

    if not enrollment.course.requires_instructor_approval:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.ACCEPTED
        )

        enrollment.accepted_at = timezone.now()

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    if enrollment.approval_status == Enrollment.ApprovalStatus.ACCEPTED:
        initialize_learning_progress(enrollment)

    return enrollment


@transaction.atomic
def mark_enrollment_partially_paid(enrollment):
    """
    Used for installment payments.

    The enrollment becomes partially paid.

    If instructor approval is not required,
    access can begin after the first successful installment.
    """

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .select_related("course")
        .get(pk=enrollment.pk)
    )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PARTIALLY_PAID
    )

    if not enrollment.course.requires_instructor_approval:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.ACCEPTED
        )

        enrollment.accepted_at = timezone.now()

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    if enrollment.approval_status == Enrollment.ApprovalStatus.ACCEPTED:
        initialize_learning_progress(enrollment)

    return enrollment


@transaction.atomic
def approve_enrollment(enrollment):
    """
    Instructor/admin approval.

    Payment still needs to be valid before actual
    learning access is granted.
    """

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .get(pk=enrollment.pk)
    )

    enrollment.approval_status = (
        Enrollment.ApprovalStatus.ACCEPTED
    )

    enrollment.accepted_at = timezone.now()

    enrollment.save(
        update_fields=[
            "approval_status",
            "accepted_at",
        ]
    )

    if has_paid_access(enrollment):
        initialize_learning_progress(enrollment)

    return enrollment


@transaction.atomic
def reject_enrollment(enrollment):
    """
    Reject an enrollment.
    """

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .get(pk=enrollment.pk)
    )

    enrollment.approval_status = (
        Enrollment.ApprovalStatus.REJECTED
    )

    enrollment.save(
        update_fields=[
            "approval_status",
        ]
    )

    return enrollment


# ============================================================
# LEARNING INITIALIZATION
# ============================================================

@transaction.atomic
def initialize_learning_progress(enrollment):
    """
    Create LearningProgress records for all published lessons.

    Only the first lesson is unlocked.

    All remaining lessons remain locked.
    """

    if not enrollment_has_access(enrollment):
        return []

    lessons = list(
        Lesson.objects
        .filter(
            module__course=enrollment.course,
        )
        .filter(
            Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True)
        )
        .order_by(
            "module__unlock_order",
            "module__order",
            "unlock_order",
            "order",
            "pk",
        )
    )

    if not lessons:
        return []

    existing_ids = set(
        LearningProgress.objects
        .filter(enrollment=enrollment)
        .values_list("lesson_id", flat=True)
    )

    progress_objects = []

    for index, lesson in enumerate(lessons):

        if lesson.id in existing_ids:
            continue

        progress_objects.append(
            LearningProgress(
                enrollment=enrollment,
                lesson=lesson,
                status=(
                    LearningProgress.Status.UNLOCKED
                    if index == 0
                    else LearningProgress.Status.LOCKED
                ),
            )
        )

    if progress_objects:
        LearningProgress.objects.bulk_create(
            progress_objects
        )

    return list(
        LearningProgress.objects
        .filter(enrollment=enrollment)
        .select_related("lesson", "lesson__module")
        .order_by(
            "lesson__module__unlock_order",
            "lesson__module__order",
            "lesson__unlock_order",
            "lesson__order",
            "lesson__pk",
        )
    )


def get_student_active_or_pending_enrollment(student, exclude_course=None):
    """
    Return the student's active or pending enrollment in another course if any.
    Students are restricted to a single course enrollment at a time.
    """
    if not student or not student.is_authenticated:
        return None

    qs = (
        Enrollment.objects
        .filter(student=student)
        .exclude(approval_status=Enrollment.ApprovalStatus.REJECTED)
        .exclude(payment_status=Enrollment.PaymentStatus.FAILED)
        .exclude(payment_status=Enrollment.PaymentStatus.REFUNDED)
        .select_related("course", "course__instructor", "course__center")
    )
    if exclude_course:
        qs = qs.exclude(course=exclude_course)

    return qs.first()

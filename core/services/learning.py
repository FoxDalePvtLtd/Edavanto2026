from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import (
    Assessment,
    Enrollment,
    LearningEvent,
    LearningProgress,
    Lesson,
    Submission,
)

from .enrollment import (
    enrollment_has_access,
    initialize_learning_progress,
)


# ============================================================
# CONSTANTS
# ============================================================

# Minimum video percentage required before considering
# the video portion complete.
VIDEO_COMPLETION_THRESHOLD = Decimal("90.00")


# ============================================================
# LESSON ORDERING
# ============================================================

def get_course_lessons(course):
    """
    Return published lessons in their actual learning order.
    """

    return list(
        Lesson.objects
        .filter(
            module__course=course,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
        )
        .select_related("module")
        .order_by(
            "module__unlock_order",
            "module__order",
            "unlock_order",
            "order",
            "pk",
        )
    )


def get_previous_lesson(enrollment, lesson):
    """
    Return the lesson immediately before the requested lesson.
    """

    lessons = get_course_lessons(enrollment.course)

    previous = None

    for current in lessons:

        if current.pk == lesson.pk:
            return previous

        previous = current

    return None


def get_next_lesson(enrollment, lesson):
    """
    Return the next published lesson.
    """

    lessons = get_course_lessons(enrollment.course)

    found_current = False

    for current in lessons:

        if found_current:
            return current

        if current.pk == lesson.pk:
            found_current = True

    return None


# ============================================================
# PROGRESS OBJECT
# ============================================================

def get_learning_progress(enrollment, lesson):
    """
    Get or create progress for a lesson.

    New progress is locked by default.
    """

    progress, created = (
        LearningProgress.objects
        .get_or_create(
            enrollment=enrollment,
            lesson=lesson,
            defaults={
                "status": LearningProgress.Status.LOCKED,
            },
        )
    )

    return progress


# ============================================================
# LESSON ACCESS
# ============================================================

def is_first_lesson(enrollment, lesson):
    """
    Determine whether this is the first published lesson.
    """

    first_lesson = (
        Lesson.objects
        .filter(
            module__course=enrollment.course,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
        )
        .order_by(
            "module__unlock_order",
            "module__order",
            "unlock_order",
            "order",
            "pk",
        )
        .first()
    )

    return first_lesson and first_lesson.pk == lesson.pk


def lesson_is_accessible(enrollment, lesson):
    """
    Final server-side lesson access check.

    Rules:

        - enrollment must be valid
        - lesson must belong to enrollment course
        - lesson must be published
        - first lesson is accessible
        - later lessons require previous lesson completion
    """

    if not enrollment_has_access(enrollment):
        return False

    if lesson.module.course_id != enrollment.course_id:
        return False

    if lesson.status != Lesson.Status.PUBLISHED:
        return False

    if not lesson.is_published:
        return False

    progress = get_learning_progress(
        enrollment,
        lesson,
    )

    if progress.status != LearningProgress.Status.LOCKED:
        return True

    if is_first_lesson(enrollment, lesson):
        progress.status = LearningProgress.Status.UNLOCKED
        progress.save(update_fields=["status", "updated_at"])
        return True

    previous_lesson = get_previous_lesson(
        enrollment,
        lesson,
    )

    if previous_lesson is None:
        return False

    previous_progress = get_learning_progress(
        enrollment,
        previous_lesson,
    )

    if previous_progress.status != LearningProgress.Status.COMPLETED:
        return False

    progress.status = LearningProgress.Status.UNLOCKED
    progress.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return True


# ============================================================
# CURRENT UNLOCKED LESSON
# ============================================================

def get_current_unlocked_lesson(enrollment):
    """
    Calculate the student's current unlocked lesson.

    This replaces the need for a current_unlocked_lesson
    field on Enrollment.
    """

    if not enrollment_has_access(enrollment):
        return None

    initialize_learning_progress(enrollment)

    progress_records = (
        LearningProgress.objects
        .filter(enrollment=enrollment)
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

    first_incomplete = None

    for progress in progress_records:

        if progress.status == LearningProgress.Status.COMPLETED:
            continue

        first_incomplete = progress
        break

    if first_incomplete is None:
        return None

    lesson = first_incomplete.lesson

    lesson_is_accessible(
        enrollment,
        lesson,
    )

    return lesson


# ============================================================
# VIDEO PROGRESS
# ============================================================

@transaction.atomic
def update_video_progress(
    enrollment,
    lesson,
    watched_percent,
    position_seconds=0,
):
    """
    Update video progress.

    The server clamps values so the client cannot send
    invalid percentages.
    """

    if not enrollment_has_access(enrollment):
        raise PermissionError(
            "You do not have access to this course."
        )

    if lesson.module.course_id != enrollment.course_id:
        raise PermissionError(
            "This lesson does not belong to your course."
        )

    if not lesson_is_accessible(
        enrollment,
        lesson,
    ):
        raise PermissionError(
            "This lesson is currently locked."
        )

    try:
        watched_percent = Decimal(
            str(watched_percent)
        )
    except Exception:
        raise ValueError(
            "Invalid watched percentage."
        )

    watched_percent = max(
        Decimal("0"),
        min(
            watched_percent,
            Decimal("100"),
        ),
    )

    try:
        position_seconds = int(
            position_seconds
        )
    except (TypeError, ValueError):
        position_seconds = 0

    position_seconds = max(
        0,
        position_seconds,
    )

    progress = get_learning_progress(
        enrollment,
        lesson,
    )

    if progress.started_at is None:
        progress.started_at = timezone.now()

    # Never move progress backwards.
    if watched_percent > progress.watched_percent:
        progress.watched_percent = watched_percent

    if position_seconds > progress.last_position_seconds:
        progress.last_position_seconds = position_seconds

    if progress.status == LearningProgress.Status.UNLOCKED:
        progress.status = (
            LearningProgress.Status.IN_PROGRESS
        )

    progress.save(
        update_fields=[
            "watched_percent",
            "last_position_seconds",
            "started_at",
            "status",
            "updated_at",
        ]
    )

    LearningEvent.objects.create(
        student=enrollment.student,
        enrollment=enrollment,
        lesson=lesson,
        event_type=LearningEvent.EventType.VIDEO_PROGRESS,
        progress=progress.watched_percent,
        metadata={
            "position_seconds": position_seconds,
        },
    )

    return progress


# ============================================================
# ASSESSMENT CHECK
# ============================================================

def get_lesson_assessments(lesson):
    """
    Assessments are attached to modules in the current model.

    A lesson therefore uses assessments belonging to its module.
    """

    return Assessment.objects.filter(
        module=lesson.module,
        is_published=True,
    ).order_by(
        "unlock_order",
        "pk",
    )


def assessment_is_passed(assessment, student):
    """
    Determine whether the student has a passing submission.
    """

    submissions = (
        Submission.objects
        .filter(
            assessment=assessment,
            student=student,
            score__isnull=False,
        )
        .order_by("-submitted_at")
    )

    for submission in submissions:

        if assessment.total_marks <= 0:
            continue

        percentage = (
            Decimal(str(submission.score))
            / Decimal(str(assessment.total_marks))
        ) * Decimal("100")

        if percentage >= assessment.pass_percentage:
            return True

    return False


def lesson_assessment_requirement_met(
    enrollment,
    lesson,
):
    """
    If the lesson's module has published assessments,
    require a passing submission.

    If no assessment exists, the lesson does not have
    an assessment requirement.
    """

    assessments = list(
        get_lesson_assessments(lesson)
    )

    if not assessments:
        return True

    for assessment in assessments:

        if not assessment_is_passed(
            assessment,
            enrollment.student,
        ):
            return False

    return True


# ============================================================
# LESSON COMPLETION
# ============================================================

@transaction.atomic
def complete_lesson(enrollment, lesson):
    """
    Complete a lesson only when all required conditions
    are satisfied.
    """

    if not enrollment_has_access(enrollment):
        raise PermissionError(
            "You do not have access to this course."
        )

    if lesson.module.course_id != enrollment.course_id:
        raise PermissionError(
            "This lesson does not belong to your course."
        )

    if not lesson_is_accessible(
        enrollment,
        lesson,
    ):
        raise PermissionError(
            "This lesson is locked."
        )

    progress = get_learning_progress(
        enrollment,
        lesson,
    )

    # --------------------------------------------------------
    # VIDEO REQUIREMENT
    # --------------------------------------------------------

    video_asset = getattr(
        lesson,
        "video_asset",
        None,
    )

    if video_asset is not None:

        if (
            progress.watched_percent
            < VIDEO_COMPLETION_THRESHOLD
        ):
            raise ValueError(
                "Please complete the required portion "
                "of the lesson video first."
            )

    # --------------------------------------------------------
    # ASSESSMENT REQUIREMENT
    # --------------------------------------------------------

    if not lesson_assessment_requirement_met(
        enrollment,
        lesson,
    ):
        raise ValueError(
            "Please complete and pass the required "
            "assessment before continuing."
        )

    # --------------------------------------------------------
    # MARK COMPLETED
    # --------------------------------------------------------

    progress.status = (
        LearningProgress.Status.COMPLETED
    )

    progress.watched_percent = max(
        progress.watched_percent,
        VIDEO_COMPLETION_THRESHOLD
        if video_asset is not None
        else progress.watched_percent,
    )

    progress.completed_at = timezone.now()

    if progress.started_at is None:
        progress.started_at = timezone.now()

    progress.save(
        update_fields=[
            "status",
            "watched_percent",
            "completed_at",
            "started_at",
            "updated_at",
        ]
    )

    LearningEvent.objects.create(
        student=enrollment.student,
        enrollment=enrollment,
        lesson=lesson,
        event_type=LearningEvent.EventType.LESSON_COMPLETED,
        progress=Decimal("100"),
    )

    # --------------------------------------------------------
    # UNLOCK NEXT LESSON
    # --------------------------------------------------------

    next_lesson = get_next_lesson(
        enrollment,
        lesson,
    )

    if next_lesson is not None:

        next_progress = get_learning_progress(
            enrollment,
            next_lesson,
        )

        if (
            next_progress.status
            == LearningProgress.Status.LOCKED
        ):
            next_progress.status = (
                LearningProgress.Status.UNLOCKED
            )

            next_progress.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

    # --------------------------------------------------------
    # UPDATE COURSE PROGRESS
    # --------------------------------------------------------

    update_enrollment_progress(enrollment)

    return progress, next_lesson


# ============================================================
# ENROLLMENT PROGRESS PERCENTAGE
# ============================================================

def update_enrollment_progress(enrollment):
    """
    Calculate overall course progress from completed lessons.
    """

    total = (
        LearningProgress.objects
        .filter(enrollment=enrollment)
        .count()
    )

    if total == 0:
        enrollment.progress_percent = Decimal("0")
        enrollment.save(
            update_fields=["progress_percent"]
        )
        return enrollment.progress_percent

    completed = (
        LearningProgress.objects
        .filter(
            enrollment=enrollment,
            status=LearningProgress.Status.COMPLETED,
        )
        .count()
    )

    percentage = (
        Decimal(completed)
        / Decimal(total)
    ) * Decimal("100")

    enrollment.progress_percent = percentage.quantize(
        Decimal("0.01")
    )

    enrollment.save(
        update_fields=[
            "progress_percent",
        ]
    )

    return enrollment.progress_percent


# ============================================================
# LESSON OPEN EVENT
# ============================================================

def record_lesson_opened(enrollment, lesson):
    """
    Record lesson opening after access validation.
    """

    if not enrollment_has_access(enrollment):
        raise PermissionError(
            "You do not have access to this course."
        )

    if not lesson_is_accessible(
        enrollment,
        lesson,
    ):
        raise PermissionError(
            "This lesson is locked."
        )

    LearningEvent.objects.create(
        student=enrollment.student,
        enrollment=enrollment,
        lesson=lesson,
        event_type=LearningEvent.EventType.LESSON_OPENED,
    )

    return True
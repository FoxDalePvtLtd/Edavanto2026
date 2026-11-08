from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from ..models import (
    Assessment,
    Enrollment,
    LearningEvent,
    LearningProgress,
    Lesson,
    Submission,
    VideoAsset,
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
# VIDEO STATE AND HELPERS
# ============================================================

class VideoState:
    NO_VIDEO = "no_video"
    EMPTY = "empty"
    PROCESSING = "processing"
    FAILED = "failed"
    READY = "ready"


def get_lesson_video_asset(lesson):
    """
    Safely return the VideoAsset attached to the lesson, or None.
    """
    try:
        return getattr(lesson, "video_asset", None)
    except VideoAsset.DoesNotExist:
        return None


def get_lesson_video_state(lesson) -> str:
    """
    Determine the video state for a lesson.
    Returns one of:
      - VideoState.NO_VIDEO: No VideoAsset record attached to lesson.
      - VideoState.EMPTY: VideoAsset record exists but has no playable file or manifest.
      - VideoState.PROCESSING: VideoAsset is pending or actively processing.
      - VideoState.FAILED: VideoAsset processing has failed.
      - VideoState.READY: VideoAsset is ready with playable media.
    """
    video_asset = get_lesson_video_asset(lesson)
    if video_asset is None:
        return VideoState.NO_VIDEO

    has_playable_source = (
        bool(video_asset.original_file)
        or bool(video_asset.hls_manifest)
        or (video_asset.duration_seconds > 0 and video_asset.processing_status == VideoAsset.ProcessingStatus.READY)
    )
    if not has_playable_source:
        return VideoState.EMPTY

    if video_asset.processing_status in (
        VideoAsset.ProcessingStatus.PENDING,
        VideoAsset.ProcessingStatus.PROCESSING,
    ):
        return VideoState.PROCESSING

    if video_asset.processing_status == VideoAsset.ProcessingStatus.FAILED:
        return VideoState.FAILED

    if video_asset.processing_status == VideoAsset.ProcessingStatus.READY:
        return VideoState.READY

    return VideoState.FAILED


def is_video_playable(lesson) -> bool:
    """
    Check if a lesson has a processed, playable video.
    """
    return get_lesson_video_state(lesson) == VideoState.READY


def lesson_has_video_requirement(lesson):
    """
    Determine whether a lesson requires video completion.
    Returns (requires_video: bool, error_message: str | None).

    - NO_VIDEO / EMPTY: (False, None)
    - PROCESSING: (True, "Video is currently processing and cannot be completed.")
    - FAILED: (True, "Video processing failed and cannot be completed.")
    - READY: (True, None)
    """
    state = get_lesson_video_state(lesson)
    if state in (VideoState.NO_VIDEO, VideoState.EMPTY):
        return False, None
    if state == VideoState.PROCESSING:
        return True, "Video is currently processing and cannot be completed."
    if state == VideoState.FAILED:
        return True, "Video processing failed and cannot be completed."
    if state == VideoState.READY:
        return True, None
    return True, "Video is not available."



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
        )
        .filter(
            Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True)
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

    if lesson.status != Lesson.Status.PUBLISHED and not lesson.is_published:
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
    duration_seconds=None,
):
    """
    Update video progress with server-side validation.

    - Validates lesson video state is READY.
    - Rejects negative or impossible positions.
    - Validates percentage against authoritative video duration.
    - Does not trust client-submitted completion percentages.
    - Prevents delayed requests from decreasing progress.
    - Records VIDEO_STARTED, VIDEO_PROGRESS milestones, and VIDEO_COMPLETED events.
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

    # Video State Check
    video_state = get_lesson_video_state(lesson)
    if video_state in (VideoState.NO_VIDEO, VideoState.EMPTY):
        raise ValueError("This lesson does not have a playable video.")
    if video_state == VideoState.PROCESSING:
        raise ValueError("Video is currently processing.")
    if video_state == VideoState.FAILED:
        raise ValueError("Video processing failed.")
    if video_state != VideoState.READY:
        raise ValueError("Video is not available for playback.")

    # Validation: watched_percent
    try:
        watched_percent = Decimal(str(watched_percent))
    except Exception:
        raise ValueError("Invalid watched percentage.")

    if watched_percent < Decimal("0"):
        raise ValueError("Watched percentage cannot be negative.")
    if watched_percent > Decimal("100"):
        raise ValueError("Watched percentage cannot exceed 100.")

    # Validation: position_seconds
    try:
        position_seconds = int(position_seconds)
    except (TypeError, ValueError):
        raise ValueError("Invalid playback position.")

    if position_seconds < 0:
        raise ValueError("Playback position cannot be negative.")

    # Video duration lookup and validation
    video_asset = get_lesson_video_asset(lesson)
    known_duration = video_asset.duration_seconds if video_asset else 0
    if not known_duration and lesson.duration_seconds:
        known_duration = lesson.duration_seconds

    if duration_seconds is not None:
        try:
            client_duration = int(duration_seconds)
        except (TypeError, ValueError):
            raise ValueError("Invalid video duration.")
        if client_duration <= 0:
            raise ValueError("Video duration must be positive.")
        if not known_duration:
            known_duration = client_duration
            if video_asset and not video_asset.duration_seconds:
                video_asset.duration_seconds = client_duration
                video_asset.save(update_fields=["duration_seconds"])

    if not known_duration or known_duration <= 0:
        raise ValueError("Video duration is missing or invalid.")

    if position_seconds > known_duration:
        raise ValueError("Playback position cannot exceed video duration.")

    # Server-calculated percentage from position against authoritative duration
    server_calc_percent = (
        Decimal(position_seconds) / Decimal(known_duration)
    ) * Decimal("100")
    server_calc_percent = min(Decimal("100.00"), max(Decimal("0.00"), server_calc_percent))

    # Do not trust client-submitted completion percentages
    if watched_percent > server_calc_percent + Decimal("2.00"):
        effective_percent = server_calc_percent
    else:
        effective_percent = watched_percent

    effective_percent = effective_percent.quantize(Decimal("0.01"))

    progress = get_learning_progress(
        enrollment,
        lesson,
    )

    if progress.started_at is None:
        progress.started_at = timezone.now()

    # Never move progress backwards (prevent delayed/out-of-order requests from decreasing stored progress)
    if effective_percent > progress.watched_percent:
        progress.watched_percent = effective_percent

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

    # 1. VIDEO_STARTED event: Record once when playback starts
    has_started_event = LearningEvent.objects.filter(
        enrollment=enrollment,
        lesson=lesson,
        event_type=LearningEvent.EventType.VIDEO_STARTED,
    ).exists()

    if not has_started_event:
        LearningEvent.objects.create(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LearningEvent.EventType.VIDEO_STARTED,
            progress=progress.watched_percent,
            metadata={"position_seconds": position_seconds},
        )

    # 2. VIDEO_PROGRESS event: Record at meaningful milestones (25%, 50%, 75%) without spamming every heartbeat
    for milestone in (Decimal("25.00"), Decimal("50.00"), Decimal("75.00")):
        if progress.watched_percent >= milestone:
            has_milestone_event = LearningEvent.objects.filter(
                enrollment=enrollment,
                lesson=lesson,
                event_type=LearningEvent.EventType.VIDEO_PROGRESS,
                metadata__milestone=int(milestone),
            ).exists()
            if not has_milestone_event:
                LearningEvent.objects.create(
                    student=enrollment.student,
                    enrollment=enrollment,
                    lesson=lesson,
                    event_type=LearningEvent.EventType.VIDEO_PROGRESS,
                    progress=progress.watched_percent,
                    metadata={
                        "milestone": int(milestone),
                        "position_seconds": position_seconds,
                    },
                )

    # 3. VIDEO_COMPLETED event: Record once when reaching the 90% threshold
    if progress.watched_percent >= VIDEO_COMPLETION_THRESHOLD:
        has_completed_event = LearningEvent.objects.filter(
            enrollment=enrollment,
            lesson=lesson,
            event_type=LearningEvent.EventType.VIDEO_COMPLETED,
        ).exists()
        if not has_completed_event:
            LearningEvent.objects.create(
                student=enrollment.student,
                enrollment=enrollment,
                lesson=lesson,
                event_type=LearningEvent.EventType.VIDEO_COMPLETED,
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
    Return published assessments attached to this lesson or module.
    """
    qs = Assessment.objects.filter(
        module=lesson.module,
        is_published=True,
    )
    if hasattr(Assessment, "lesson"):
        qs = qs.filter(Q(lesson=lesson) | Q(lesson__isnull=True))
    return qs.order_by("unlock_order", "pk")


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

    total_marks = assessment.total_marks
    if not total_marks or total_marks <= 0:
        total_marks = assessment.questions.aggregate(total=Sum("marks"))["total"] or 0

    if total_marks <= 0:
        return submissions.exists()

    for submission in submissions:
        percentage = (
            Decimal(str(submission.score))
            / Decimal(str(total_marks))
        ) * Decimal("100")

        if percentage >= Decimal(str(assessment.pass_percentage)):
            return True

    return False


def lesson_assessment_requirement_met(
    enrollment,
    lesson,
):
    """
    Check if the assessment requirement for the lesson is met:
    1. If the lesson has its own published assessments, student must pass them.
    2. If the lesson is the last published lesson in the module, student must pass module-level assessments.
    3. Intermediate lessons in the module are not blocked by future module assessments.
    """
    # 1. Lesson-specific assessments
    lesson_assessments = list(
        Assessment.objects.filter(
            lesson=lesson,
            is_published=True,
        )
    )
    for assessment in lesson_assessments:
        if not assessment_is_passed(assessment, enrollment.student):
            return False

    # 2. Module-level assessments (enforced on the last published lesson of the module)
    is_last_in_module = not lesson.module.lessons.filter(
        Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True),
        order__gt=lesson.order,
    ).exists()

    if is_last_in_module:
        module_assessments = Assessment.objects.filter(
            module=lesson.module,
            lesson__isnull=True,
            is_published=True,
        )
        for assessment in module_assessments:
            if not assessment_is_passed(assessment, enrollment.student):
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

    requires_video, video_error = lesson_has_video_requirement(lesson)
    if video_error:
        raise ValueError(video_error)

    has_video = bool(
        video_asset
        and (
            video_asset.original_file
            or video_asset.hls_manifest
        )
    )

    if has_video:
        if progress.watched_percent < VIDEO_COMPLETION_THRESHOLD:
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
    if has_video
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

    # Prevent duplicate LESSON_COMPLETED events
    has_lesson_completed_event = LearningEvent.objects.filter(
        enrollment=enrollment,
        lesson=lesson,
        event_type=LearningEvent.EventType.LESSON_COMPLETED,
    ).exists()

    if not has_lesson_completed_event:
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
    Denominator is the total number of published lessons in the course.
    """

    total = (
        Lesson.objects
        .filter(
            module__course=enrollment.course,
        )
        .filter(
            Q(status=Lesson.Status.PUBLISHED) | Q(is_published=True)
        )
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

    # Clamp to 100 max
    percentage = min(Decimal("100"), percentage)

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
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from core.models import (
    User,
    Course,
    Module,
    Lesson,
    VideoAsset,
    Enrollment,
    LearningProgress,
)
from core.services.learning import (
    lesson_is_accessible,
    complete_lesson,
    update_enrollment_progress,
)


class StudyWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create student and instructor
        cls.student = User.objects.create_user(
            username="teststudent",
            email="student@edvanto.test",
            password="Strong-pass-123!",
            role=User.Role.STUDENT,
            first_name="Jane",
            last_name="Doe",
        )
        cls.instructor = User.objects.create_user(
            username="testinstructor",
            email="instructor@edvanto.test",
            password="Strong-pass-123!",
            role=User.Role.INSTRUCTOR,
        )

        # Create online course
        cls.course = Course.objects.create(
            title="Django Advanced",
            slug="django-advanced",
            description="Deep dive into Django",
            category=Course.Category.DEVELOPMENT,
            mode=Course.Mode.ONLINE,
            price=Decimal("2000.00"),
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
        )

        # Create Module 1 with 2 lessons
        cls.mod1 = Module.objects.create(
            course=cls.course,
            title="Module 1: Foundations",
            order=1,
            unlock_order=1,
        )
        cls.lesson1 = Lesson.objects.create(
            module=cls.mod1,
            title="Lesson 1.1: Architecture",
            order=1,
            unlock_order=1,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=300,
        )
        cls.lesson2 = Lesson.objects.create(
            module=cls.mod1,
            title="Lesson 1.2: Models",
            order=2,
            unlock_order=2,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=400,
        )

        # Create Module 2 with 1 lesson
        cls.mod2 = Module.objects.create(
            course=cls.course,
            title="Module 2: Advanced Views",
            order=2,
            unlock_order=2,
        )
        cls.lesson3 = Lesson.objects.create(
            module=cls.mod2,
            title="Lesson 2.1: Class Based Views",
            order=1,
            unlock_order=1,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=500,
        )

        # Attach video asset to lesson 1
        cls.video1 = VideoAsset.objects.create(
            lesson=cls.lesson1,
            duration_seconds=300,
            processing_status=VideoAsset.ProcessingStatus.READY,
        )

    def setUp(self):
        # Create active, paid enrollment
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.ACCEPTED,
        )
        self.client.force_login(self.student)

    def test_first_lesson_is_accessible_and_subsequent_are_locked(self):
        """Lesson 1 should be accessible (unlocked) while Lesson 2 and 3 remain locked initially."""
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson1))
        self.assertFalse(lesson_is_accessible(self.enrollment, self.lesson2))
        self.assertFalse(lesson_is_accessible(self.enrollment, self.lesson3))

    def test_direct_access_to_locked_lesson_redirects(self):
        """Student attempting direct URL access to a locked lesson is redirected with warning."""
        response = self.client.get(reverse("core:lesson", kwargs={"lesson_id": self.lesson2.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_video_progress_api_updates_progress(self):
        """Posting to lesson progress API clamps and saves watched percentage and position."""
        # Ensure progress record initialized
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson1))
        url = reverse("core:lesson_progress_api", kwargs={"lesson_id": self.lesson1.pk})

        response = self.client.post(url, {"watched_percent": "45.5", "position_seconds": "136"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["watched_percent"], 45.5)
        self.assertEqual(data["position_seconds"], 136)

        prog = LearningProgress.objects.get(enrollment=self.enrollment, lesson=self.lesson1)
        self.assertEqual(prog.watched_percent, Decimal("45.50"))
        self.assertEqual(prog.last_position_seconds, 136)

    def test_cannot_complete_video_lesson_without_90_percent(self):
        """Lesson with video requires >=90% watch threshold before completion."""
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson1))
        prog = LearningProgress.objects.get(enrollment=self.enrollment, lesson=self.lesson1)
        prog.watched_percent = Decimal("50.00")
        prog.save()

        complete_url = reverse("core:lesson_complete_api", kwargs={"lesson_id": self.lesson1.pk})
        response = self.client.post(complete_url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("video", response.json()["error"].lower())

    def test_completion_unlocks_next_lesson_and_updates_progress(self):
        """Completing lesson 1 unlocks lesson 2 and accurately recalculates progress (1/3 = 33.33%)."""
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson1))
        prog = LearningProgress.objects.get(enrollment=self.enrollment, lesson=self.lesson1)
        prog.watched_percent = Decimal("95.00")
        prog.save()

        complete_url = reverse("core:lesson_complete_api", kwargs={"lesson_id": self.lesson1.pk})
        response = self.client.post(complete_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["next_lesson_id"], self.lesson2.pk)

        # Lesson 2 is now unlocked and accessible
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson2))

        # Check enrollment progress calculation: 1 out of 3 published lessons = 33.33%
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress_percent, Decimal("33.33"))

    def test_cross_module_sequential_unlock(self):
        """Completing lesson 2 in Module 1 unlocks lesson 3 in Module 2."""
        # Complete lesson 1
        prog1 = LearningProgress.objects.create(
            enrollment=self.enrollment,
            lesson=self.lesson1,
            status=LearningProgress.Status.COMPLETED,
            watched_percent=Decimal("100.00"),
        )
        # Lesson 2 has no video asset, can be completed directly
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson2))
        complete_lesson(self.enrollment, self.lesson2)

        # Lesson 3 in Module 2 should now be accessible
        self.assertTrue(lesson_is_accessible(self.enrollment, self.lesson3))

        # Check enrollment progress: 2 out of 3 = 66.67%
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress_percent, Decimal("66.67"))

    def test_student_workspace_view_renders_curriculum_states(self):
        """The course_dashboard view passes curriculum with correct completed and locked states."""
        # Lesson 1 completed, Lesson 2 unlocked, Lesson 3 locked
        LearningProgress.objects.create(
            enrollment=self.enrollment,
            lesson=self.lesson1,
            status=LearningProgress.Status.COMPLETED,
            watched_percent=Decimal("100.00"),
        )
        LearningProgress.objects.create(
            enrollment=self.enrollment,
            lesson=self.lesson2,
            status=LearningProgress.Status.UNLOCKED,
        )
        LearningProgress.objects.create(
            enrollment=self.enrollment,
            lesson=self.lesson3,
            status=LearningProgress.Status.LOCKED,
        )
        update_enrollment_progress(self.enrollment)

        response = self.client.get(reverse("core:course_dashboard", kwargs={"slug": self.course.slug}))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        # Lesson 1 shows completed
        self.assertIn("Completed", content)
        # Lesson 2 shows start / continue
        self.assertIn("Lesson 1.2: Models", content)
        # Lesson 3 shows locked
        self.assertIn("Lesson 2.1: Class Based Views", content)
        self.assertIn("Locked", content)

    def test_admin_base_footer_renders_cleanly(self):
        """Admin panel renders the new footer without broken characters and with inner container."""
        admin = User.objects.create_superuser(
            username="superadmin",
            email="admin@edvanto.test",
            password="Strong-admin-pass-123!",
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("admin_panel:dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        idx = content.find("Lesson 1.1: Architecture")
        print("DEBUG HTML SNIPPET:\n", content[idx-100:idx+600])
        self.assertIn("edvanto-footer-inner", content)
        self.assertIn("&bull;", content)
        self.assertNotIn("\ufffd", content)


from core.models import LearningEvent
from core.services.learning import (
    VideoState,
    get_lesson_video_state,
    is_video_playable,
    lesson_has_video_requirement,
    update_video_progress,
)


class VideoTrackingAndCompletionPhase1Tests(TestCase):
    """
    Automated test suite verifying all Phase 1 requirements:
    - Video state handling (no video, empty, processing, failed, ready)
    - Video progress tracking & validation (clamping, rejecting invalid values, position vs duration)
    - 90% completion threshold backend enforcement
    - Learning event tracking (video_started, video_progress milestones, video_completed, no duplicates)
    - Streaming protection against unready videos
    - Student UI template rendering based on video state
    """

    def setUp(self):
        self.student = User.objects.create_user(
            username="phase1_student",
            email="phase1_student@edvanto.test",
            password="Strong-pass-123!",
            role=User.Role.STUDENT,
            first_name="Alice",
            last_name="Smith",
        )
        self.instructor = User.objects.create_user(
            username="phase1_instructor",
            email="phase1_instructor@edvanto.test",
            password="Strong-pass-123!",
            role=User.Role.INSTRUCTOR,
        )
        self.course = Course.objects.create(
            title="Video Architecture Course",
            slug="video-architecture-course",
            description="Testing Phase 1 Video Tracking",
            category=Course.Category.DEVELOPMENT,
            mode=Course.Mode.ONLINE,
            price=Decimal("1500.00"),
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Module 1: Video Fundamentals",
            order=1,
            unlock_order=1,
        )
        self.lesson_ready = Lesson.objects.create(
            module=self.module,
            title="Lesson 1: Playable Video Lesson",
            order=1,
            unlock_order=1,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=300,
        )
        self.video_ready = VideoAsset.objects.create(
            lesson=self.lesson_ready,
            original_file="videos/original/playable.mp4",
            duration_seconds=300,
            processing_status=VideoAsset.ProcessingStatus.READY,
        )

        self.lesson_no_video = Lesson.objects.create(
            module=self.module,
            title="Lesson 2: Reading Material Only",
            order=2,
            unlock_order=2,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=0,
        )

        self.lesson_empty = Lesson.objects.create(
            module=self.module,
            title="Lesson 3: Empty Video Asset",
            order=3,
            unlock_order=3,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=0,
        )
        self.video_empty = VideoAsset.objects.create(
            lesson=self.lesson_empty,
            original_file="",
            hls_manifest="",
            duration_seconds=0,
            processing_status=VideoAsset.ProcessingStatus.PENDING,
        )

        self.lesson_processing = Lesson.objects.create(
            module=self.module,
            title="Lesson 4: Processing Video Lesson",
            order=4,
            unlock_order=4,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=200,
        )
        self.video_processing = VideoAsset.objects.create(
            lesson=self.lesson_processing,
            original_file="videos/original/processing.mp4",
            duration_seconds=200,
            processing_status=VideoAsset.ProcessingStatus.PROCESSING,
        )

        self.lesson_failed = Lesson.objects.create(
            module=self.module,
            title="Lesson 5: Failed Video Lesson",
            order=5,
            unlock_order=5,
            status=Lesson.Status.PUBLISHED,
            is_published=True,
            duration_seconds=180,
        )
        self.video_failed = VideoAsset.objects.create(
            lesson=self.lesson_failed,
            original_file="videos/original/failed.mp4",
            duration_seconds=180,
            processing_status=VideoAsset.ProcessingStatus.FAILED,
            processing_error="Transcoding error",
        )

        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.ACCEPTED,
        )
        for l in (self.lesson_ready, self.lesson_no_video, self.lesson_empty, self.lesson_processing, self.lesson_failed):
            LearningProgress.objects.create(
                enrollment=self.enrollment,
                lesson=l,
                status=LearningProgress.Status.UNLOCKED,
            )
        self.client.force_login(self.student)

    # -------------------------------------------------------------------------
    # 1. VIDEO STATE TESTS
    # -------------------------------------------------------------------------
    def test_state_no_video_asset_record(self):
        state = get_lesson_video_state(self.lesson_no_video)
        self.assertEqual(state, VideoState.NO_VIDEO)
        self.assertFalse(is_video_playable(self.lesson_no_video))
        req, err = lesson_has_video_requirement(self.lesson_no_video)
        self.assertFalse(req)
        self.assertIsNone(err)

    def test_state_empty_video_asset_record(self):
        state = get_lesson_video_state(self.lesson_empty)
        self.assertEqual(state, VideoState.EMPTY)
        self.assertFalse(is_video_playable(self.lesson_empty))
        req, err = lesson_has_video_requirement(self.lesson_empty)
        self.assertFalse(req)
        self.assertIsNone(err)

    def test_state_uploaded_and_processing_video(self):
        state = get_lesson_video_state(self.lesson_processing)
        self.assertEqual(state, VideoState.PROCESSING)
        self.assertFalse(is_video_playable(self.lesson_processing))
        req, err = lesson_has_video_requirement(self.lesson_processing)
        self.assertTrue(req)
        self.assertIn("processing", err.lower())

    def test_state_failed_video(self):
        state = get_lesson_video_state(self.lesson_failed)
        self.assertEqual(state, VideoState.FAILED)
        self.assertFalse(is_video_playable(self.lesson_failed))
        req, err = lesson_has_video_requirement(self.lesson_failed)
        self.assertTrue(req)
        self.assertIn("failed", err.lower())

    def test_state_successfully_processed_ready_video(self):
        state = get_lesson_video_state(self.lesson_ready)
        self.assertEqual(state, VideoState.READY)
        self.assertTrue(is_video_playable(self.lesson_ready))
        req, err = lesson_has_video_requirement(self.lesson_ready)
        self.assertTrue(req)
        self.assertIsNone(err)

    # -------------------------------------------------------------------------
    # 2. PROGRESS TRACKING & BACKEND VALIDATION TESTS
    # -------------------------------------------------------------------------
    def test_progress_valid_playback_tracking(self):
        # 60 seconds out of 300s = 20.00%
        prog = update_video_progress(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            watched_percent="20.00",
            position_seconds=60,
        )
        self.assertEqual(prog.watched_percent, Decimal("20.00"))
        self.assertEqual(prog.last_position_seconds, 60)
        self.assertEqual(prog.status, LearningProgress.Status.IN_PROGRESS)

    def test_progress_zero_progress(self):
        prog = update_video_progress(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            watched_percent="0.00",
            position_seconds=0,
        )
        self.assertEqual(prog.watched_percent, Decimal("0.00"))
        self.assertEqual(prog.last_position_seconds, 0)

    def test_progress_reject_negative_values(self):
        with self.assertRaises(ValueError):
            update_video_progress(
                enrollment=self.enrollment,
                lesson=self.lesson_ready,
                watched_percent="-5.00",
                position_seconds=10,
            )
        with self.assertRaises(ValueError):
            update_video_progress(
                enrollment=self.enrollment,
                lesson=self.lesson_ready,
                watched_percent="10.00",
                position_seconds=-10,
            )

    def test_progress_reject_invalid_percentage(self):
        with self.assertRaises(ValueError):
            update_video_progress(
                enrollment=self.enrollment,
                lesson=self.lesson_ready,
                watched_percent="150.00",
                position_seconds=50,
            )

    def test_progress_reject_position_beyond_duration(self):
        # Video is 300 seconds, position 350 must be rejected
        with self.assertRaises(ValueError):
            update_video_progress(
                enrollment=self.enrollment,
                lesson=self.lesson_ready,
                watched_percent="50.00",
                position_seconds=350,
            )

    def test_progress_reject_invalid_duration_values(self):
        with self.assertRaises(ValueError):
            update_video_progress(
                enrollment=self.enrollment,
                lesson=self.lesson_ready,
                watched_percent="10.00",
                position_seconds=10,
                duration_seconds=-100,
            )

    def test_progress_client_percentage_manipulation_not_trusted(self):
        # Client claims 95% completion, but position is only 30s of 300s (10%)
        prog = update_video_progress(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            watched_percent="95.00",
            position_seconds=30,
        )
        # Server clamps to true calculated percentage from position (10.00%)
        self.assertEqual(prog.watched_percent, Decimal("10.00"))
        self.assertEqual(prog.last_position_seconds, 30)

    def test_progress_repeated_requests_safe(self):
        update_video_progress(self.enrollment, self.lesson_ready, "20.00", 60)
        update_video_progress(self.enrollment, self.lesson_ready, "20.00", 60)
        prog = update_video_progress(self.enrollment, self.lesson_ready, "20.00", 60)
        self.assertEqual(prog.watched_percent, Decimal("20.00"))

    def test_progress_out_of_order_requests_do_not_decrease_progress(self):
        update_video_progress(self.enrollment, self.lesson_ready, "50.00", 150)
        # A delayed or re-watched position of 30s (10%) should not decrease progress from 50%
        prog = update_video_progress(self.enrollment, self.lesson_ready, "10.00", 30)
        self.assertEqual(prog.watched_percent, Decimal("50.00"))

    def test_progress_rejected_on_unready_video(self):
        # Processing video
        with self.assertRaises(ValueError):
            update_video_progress(self.enrollment, self.lesson_processing, "10.00", 10)
        # Failed video
        with self.assertRaises(ValueError):
            update_video_progress(self.enrollment, self.lesson_failed, "10.00", 10)
        # No video lesson
        with self.assertRaises(ValueError):
            update_video_progress(self.enrollment, self.lesson_no_video, "10.00", 10)

    # -------------------------------------------------------------------------
    # 3. 90% COMPLETION THRESHOLD TESTS
    # -------------------------------------------------------------------------
    def test_completion_50_percent_remains_incomplete(self):
        prog = update_video_progress(self.enrollment, self.lesson_ready, "50.00", 150)
        with self.assertRaises(ValueError) as ctx:
            complete_lesson(self.enrollment, self.lesson_ready)
        self.assertIn("video", str(ctx.exception).lower())

    def test_completion_89_percent_remains_incomplete(self):
        # 89% = 267s of 300s
        prog = update_video_progress(self.enrollment, self.lesson_ready, "89.00", 267)
        with self.assertRaises(ValueError) as ctx:
            complete_lesson(self.enrollment, self.lesson_ready)
        self.assertIn("video", str(ctx.exception).lower())

    def test_completion_at_exactly_90_percent_meets_threshold(self):
        # 90% = 270s of 300s
        update_video_progress(self.enrollment, self.lesson_ready, "90.00", 270)
        prog, _ = complete_lesson(self.enrollment, self.lesson_ready)
        self.assertEqual(prog.status, LearningProgress.Status.COMPLETED)
        self.assertIsNotNone(prog.completed_at)

    def test_completion_above_90_percent_meets_threshold(self):
        # 95% = 285s of 300s
        update_video_progress(self.enrollment, self.lesson_ready, "95.00", 285)
        prog, _ = complete_lesson(self.enrollment, self.lesson_ready)
        self.assertEqual(prog.status, LearningProgress.Status.COMPLETED)

    def test_completion_empty_video_does_not_block_lesson(self):
        # Empty video asset has no playable video, completion should proceed
        prog, _ = complete_lesson(self.enrollment, self.lesson_empty)
        self.assertEqual(prog.status, LearningProgress.Status.COMPLETED)

    def test_completion_no_video_lesson_completes_directly(self):
        # Lesson without video asset completes without video check
        prog, _ = complete_lesson(self.enrollment, self.lesson_no_video)
        self.assertEqual(prog.status, LearningProgress.Status.COMPLETED)

    def test_completion_processing_video_cannot_be_completed(self):
        with self.assertRaises(ValueError) as ctx:
            complete_lesson(self.enrollment, self.lesson_processing)
        self.assertIn("processing", str(ctx.exception).lower())

    def test_completion_failed_video_cannot_be_completed(self):
        with self.assertRaises(ValueError) as ctx:
            complete_lesson(self.enrollment, self.lesson_failed)
        self.assertIn("failed", str(ctx.exception).lower())

    def test_direct_completion_request_cannot_bypass_90_percent(self):
        # Calling API directly when progress is below 90% must return 400
        url = reverse("core:lesson_complete_api", kwargs={"lesson_id": self.lesson_ready.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertIn("video", response.json()["error"].lower())

    # -------------------------------------------------------------------------
    # 4. LEARNING EVENT TRACKING TESTS
    # -------------------------------------------------------------------------
    def test_event_video_started_recorded_once(self):
        update_video_progress(self.enrollment, self.lesson_ready, "5.00", 15)
        start_events = LearningEvent.objects.filter(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            event_type=LearningEvent.EventType.VIDEO_STARTED,
        )
        self.assertEqual(start_events.count(), 1)

        # Subsequent progress must NOT create a second VIDEO_STARTED event
        update_video_progress(self.enrollment, self.lesson_ready, "10.00", 30)
        self.assertEqual(start_events.count(), 1)

    def test_event_video_progress_milestones_and_no_heartbeat_spam(self):
        # Send frequent heartbeats from 1% to 15%
        for s in range(3, 45, 3):
            pct = Decimal(s) / Decimal(300) * Decimal(100)
            update_video_progress(self.enrollment, self.lesson_ready, pct, s)

        # Below 25% milestone, no milestone progress event is created
        milestone_events = LearningEvent.objects.filter(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            event_type=LearningEvent.EventType.VIDEO_PROGRESS,
        )
        self.assertEqual(milestone_events.count(), 0)

        # Cross 25% milestone (75s of 300s = 25%)
        update_video_progress(self.enrollment, self.lesson_ready, "25.00", 75)
        self.assertEqual(milestone_events.count(), 1)

        # Subsequent heartbeat at 26% does not spam another progress event
        update_video_progress(self.enrollment, self.lesson_ready, "26.00", 78)
        self.assertEqual(milestone_events.count(), 1)

        # Cross 50% milestone (150s of 300s)
        update_video_progress(self.enrollment, self.lesson_ready, "50.00", 150)
        self.assertEqual(milestone_events.count(), 2)

    def test_event_video_completed_recorded_at_90_percent(self):
        update_video_progress(self.enrollment, self.lesson_ready, "90.00", 270)
        completed_events = LearningEvent.objects.filter(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            event_type=LearningEvent.EventType.VIDEO_COMPLETED,
        )
        self.assertEqual(completed_events.count(), 1)

        # Repeated progress beyond 90% does not duplicate VIDEO_COMPLETED event
        update_video_progress(self.enrollment, self.lesson_ready, "95.00", 285)
        self.assertEqual(completed_events.count(), 1)

    def test_event_no_duplicate_completion_events_on_complete_lesson(self):
        update_video_progress(self.enrollment, self.lesson_ready, "90.00", 270)
        complete_lesson(self.enrollment, self.lesson_ready)
        lesson_events = LearningEvent.objects.filter(
            enrollment=self.enrollment,
            lesson=self.lesson_ready,
            event_type=LearningEvent.EventType.LESSON_COMPLETED,
        )
        self.assertEqual(lesson_events.count(), 1)

        # Call again
        complete_lesson(self.enrollment, self.lesson_ready)
        self.assertEqual(lesson_events.count(), 1)

    # -------------------------------------------------------------------------
    # 5. STREAMING VIEW RESTRICTION TESTS
    # -------------------------------------------------------------------------
    def test_stream_processing_video_forbidden(self):
        url = reverse("core:stream_lesson_video", kwargs={"lesson_id": self.lesson_processing.pk})
        response = self.client.get(url, HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(response.status_code, 403)

    def test_stream_failed_video_forbidden(self):
        url = reverse("core:stream_lesson_video", kwargs={"lesson_id": self.lesson_failed.pk})
        response = self.client.get(url, HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(response.status_code, 403)

    def test_stream_empty_video_not_found(self):
        url = reverse("core:stream_lesson_video", kwargs={"lesson_id": self.lesson_empty.pk})
        response = self.client.get(url, HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual(response.status_code, 404)

    # -------------------------------------------------------------------------
    # 6. UI & TEMPLATE RENDERING TESTS
    # -------------------------------------------------------------------------
    def test_ui_renders_player_for_ready_video(self):
        url = reverse("core:lesson", kwargs={"lesson_id": self.lesson_ready.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('id="lesson-video"', content)
        self.assertIn("Protected Video Lesson", content)

    def test_ui_renders_processing_alert_for_processing_video(self):
        url = reverse("core:lesson", kwargs={"lesson_id": self.lesson_processing.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn('id="lesson-video"', content)
        self.assertIn("Video Processing", content)

    def test_ui_renders_failed_alert_for_failed_video(self):
        url = reverse("core:lesson", kwargs={"lesson_id": self.lesson_failed.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn('id="lesson-video"', content)
        self.assertIn("Video Unavailable", content)

    def test_ui_renders_no_video_notice_for_no_video_lesson(self):
        url = reverse("core:lesson", kwargs={"lesson_id": self.lesson_no_video.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn('id="lesson-video"', content)
        self.assertIn("Reading &amp; Study Lesson", content)

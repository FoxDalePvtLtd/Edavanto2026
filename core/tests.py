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

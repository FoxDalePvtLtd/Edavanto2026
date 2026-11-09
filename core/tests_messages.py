from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, Course, Module, Lesson, Enrollment,
    Assessment, Question, DoubtThread, DoubtMessage,
)


class MessageRoutingAndIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "Secr3tP@ss123"

        self.student = User.objects.create_user(
            username="student@edvanto.test",
            email="student@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
            first_name="Alice",
            last_name="Learner",
        )

        self.admin = User.objects.create_superuser(
            username="admin@edvanto.test",
            email="admin@edvanto.test",
            password=self.password,
            role=User.Role.ADMIN,
            first_name="Admin",
            last_name="Super",
        )

        self.course = Course.objects.create(
            title="Python Mastery",
            slug="python-mastery",
            mode=Course.Mode.ONLINE,
            price=Decimal("199.00"),
            status=Course.Status.PUBLISHED,
        )

        self.module = Module.objects.create(
            course=self.course,
            title="Module 1: Basics",
            order=1,
            unlock_order=1,
        )

        self.lesson1 = Lesson.objects.create(
            module=self.module,
            title="Lesson 1: Intro",
            order=1,
            unlock_order=1,
            is_published=True,
            status=Lesson.Status.PUBLISHED,
        )

        self.lesson2 = Lesson.objects.create(
            module=self.module,
            title="Lesson 2: Advanced",
            order=2,
            unlock_order=2,
            is_published=True,
            status=Lesson.Status.PUBLISHED,
        )

        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.ACCEPTED,
        )

    # ========================================================
    # AUTHENTICATION MESSAGE FLOWS
    # ========================================================

    def test_student_login_renders_message_on_dashboard_not_courses(self):
        """Successful student login must render 'Login successful.' on student dashboard, not on courses."""
        response = self.client.post(
            reverse("core:login"),
            {"email": self.student.email, "password": self.password},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("core:dashboard"))
        content = response.content.decode("utf-8")
        self.assertIn("Welcome Back!", content)
        self.assertIn("You have successfully logged in to Edvanto.", content)
        # Verify rendered in Edvanto toast component
        self.assertIn("data-edvanto-toast", content)

        # Subsequent visit to Courses page must NOT contain the consumed login message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertEqual(courses_res.status_code, 200)
        courses_content = courses_res.content.decode("utf-8")
        self.assertNotIn("Welcome Back!", courses_content)
        self.assertNotIn("You have successfully logged in to Edvanto.", courses_content)
        self.assertNotIn("data-edvanto-toast", courses_content)

    def test_admin_login_renders_message_on_admin_dashboard(self):
        """Successful admin login must render message on admin dashboard only."""
        response = self.client.post(
            reverse("core:login"),
            {"email": self.admin.email, "password": self.password},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("admin_panel:dashboard"))
        content = response.content.decode("utf-8")
        self.assertIn("Welcome to the Edvanto administration panel.", content)

        # Must not appear on public courses page
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Welcome to the Edvanto administration panel.", courses_res.content.decode("utf-8"))

    def test_invalid_login_renders_error_on_login_page_only(self):
        """Failed login must show error on login page and not leak to other pages."""
        response = self.client.post(
            reverse("core:login"),
            {"email": self.student.email, "password": "WrongPassword!"},
        )
        self.assertEqual(response.status_code, 401)
        content = response.content.decode("utf-8")
        self.assertIn("Invalid email or password.", content)

        # Subsequent visit to Courses page must not show the error
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Invalid email or password.", courses_res.content.decode("utf-8"))

    def test_logout_renders_message_on_home_page_only(self):
        """Logout confirmation message must appear only on home page and not leak to courses."""
        self.client.force_login(self.student)
        response = self.client.post(reverse("core:logout"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("core:home"))
        content = response.content.decode("utf-8")
        self.assertIn("Logged Out Successfully", content)
        self.assertIn("You have been logged out successfully. See you again!", content)

        # Visiting courses must not show the logout message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Logged Out Successfully", courses_res.content.decode("utf-8"))
        self.assertNotIn("You have been logged out successfully.", courses_res.content.decode("utf-8"))

    # ========================================================
    # STUDENT DASHBOARD WORKFLOW MESSAGES
    # ========================================================

    def test_locked_lesson_message_renders_on_dashboard_not_courses(self):
        """Accessing a locked lesson must redirect to dashboard with warning, not leak to courses."""
        self.client.force_login(self.student)
        # Lesson 2 is locked
        response = self.client.get(
            reverse("core:lesson", kwargs={"lesson_id": self.lesson2.pk}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("core:dashboard"))
        content = response.content.decode("utf-8")
        self.assertIn("This lesson is currently locked.", content)

        # Courses page must not display this dashboard message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("This lesson is currently locked.", courses_res.content.decode("utf-8"))

    def test_doubt_submission_message_stays_in_doubt_workflow(self):
        """Submitting a doubt must render success on doubt_detail and not leak to courses."""
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("core:create_doubt", kwargs={"lesson_id": self.lesson1.pk}),
            {"subject": "How does decorators work?", "message": "Need clarification on python decorators."},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        thread = DoubtThread.objects.filter(student=self.student).first()
        self.assertIsNotNone(thread)
        self.assertRedirects(response, reverse("core:doubt_detail", kwargs={"thread_id": thread.pk}))
        content = response.content.decode("utf-8")
        self.assertIn("Your doubt regarding", content)

        # Courses page must not display this doubt message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Your doubt regarding", courses_res.content.decode("utf-8"))

    def test_assessment_submission_message_stays_in_assessment_workflow(self):
        """Submitting an assessment must display success on result page and not leak to courses."""
        assessment = Assessment.objects.create(
            module=self.module,
            title="Python Quiz 1",
            is_published=True,
            pass_percentage=50,
            attempts_allowed=2,
        )
        question = Question.objects.create(
            assessment=assessment,
            question_text="What is Python?",
            question_type=Question.QuestionType.MCQ,
            order=1,
            marks=10,
            options=["Snake", "Programming language", "Operating system", "Browser"],
            correct_answer="Programming language",
        )

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("core:take_assessment", kwargs={"assessment_id": assessment.pk}),
            {f"question_{question.pk}": "Programming language"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("submitted successfully!", content)

        # Courses page must not display this assessment message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("submitted successfully!", courses_res.content.decode("utf-8"))

    # ========================================================
    # ADMIN PANEL ISOLATION & NO DUPLICATE RENDERING
    # ========================================================

    def test_admin_messages_stay_in_admin_panel(self):
        """Admin actions must display messages within admin and not leak to public or student dashboard."""
        self.client.force_login(self.admin)
        # Toggle user active state
        response = self.client.post(
            reverse("admin_panel:user_toggle_active", kwargs={"user_id": self.student.pk}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("admin_panel:user_list"))
        content = response.content.decode("utf-8")
        self.assertIn("User deactivated successfully.", content)
        # Admin uses edvantoToast
        self.assertIn("window.edvantoToast", content)

        # No duplicate HTML alert block in admin user list
        self.assertNotIn('<div class="alert alert-', content)

        # Public courses page must not show the admin message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("User deactivated successfully.", courses_res.content.decode("utf-8"))

    # ========================================================
    # ADDITIONAL WORKFLOW TESTS
    # ========================================================

    def test_student_without_enrollment_logs_in_to_dashboard_not_courses(self):
        """A student with no enrollments must still arrive at dashboard with login message and not leak to courses."""
        unenrolled_student = User.objects.create_user(
            username="unenrolled@edvanto.test",
            email="unenrolled@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
            first_name="Bob",
            last_name="Newbie",
        )
        response = self.client.post(
            reverse("core:login"),
            {"email": unenrolled_student.email, "password": self.password},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("core:dashboard"))
        content = response.content.decode("utf-8")
        self.assertIn("Welcome Back!", content)
        self.assertIn("You have successfully logged in to Edvanto.", content)
        # Must NOT bounce with warning to courses
        self.assertNotIn("Please select a course to access your student dashboard.", content)

        # Courses page must not show the message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Welcome Back!", courses_res.content.decode("utf-8"))

    def test_offline_payment_submission_message_stays_on_dashboard(self):
        """Offline payment request must redirect to dashboard and show message once."""
        other_course = Course.objects.create(
            title="React Basics",
            slug="react-basics",
            mode=Course.Mode.ONLINE,
            price=Decimal("150.00"),
            status=Course.Status.PUBLISHED,
        )
        fresh_student = User.objects.create_user(
            username="fresh@edvanto.test",
            email="fresh@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.client.force_login(fresh_student)
        response = self.client.post(
            reverse("core:offline_payment_request", kwargs={"slug": other_course.slug}),
            {
                "payment_mode": "UPI",
                "transaction_reference": "UPI123456789",
                "payment_date": "2026-11-08",
                "notes": "Payment done via GPay",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("core:dashboard"))
        content = response.content.decode("utf-8")
        self.assertIn("Your offline payment request", content)
        self.assertIn("React Basics", content)

        # Courses page must not show the payment message
        courses_res = self.client.get(reverse("core:courses"))
        self.assertNotIn("Your offline payment request", courses_res.content.decode("utf-8"))

    def test_doubt_reply_and_resolve_messages_stay_in_thread(self):
        """Replying to or resolving a doubt must keep messages in doubt detail."""
        thread = DoubtThread.objects.create(
            student=self.student,
            enrollment=self.enrollment,
            lesson=self.lesson1,
            subject="Question on loops",
            status=DoubtThread.Status.OPEN,
        )
        DoubtMessage.objects.create(
            thread=thread,
            sender=self.student,
            message="Can you explain for loops?",
        )
        self.client.force_login(self.student)

        # 1. Post reply
        reply_res = self.client.post(
            reverse("core:doubt_reply", kwargs={"thread_id": thread.pk}),
            {"message": "I still have a doubt about break vs continue."},
            follow=True,
        )
        self.assertEqual(reply_res.status_code, 200)
        self.assertRedirects(reply_res, reverse("core:doubt_detail", kwargs={"thread_id": thread.pk}))
        self.assertIn("Follow-up message sent.", reply_res.content.decode("utf-8"))

        # 2. Mark resolved
        resolve_res = self.client.post(
            reverse("core:doubt_resolve", kwargs={"thread_id": thread.pk}),
            follow=True,
        )
        self.assertEqual(resolve_res.status_code, 200)
        self.assertRedirects(resolve_res, reverse("core:doubt_detail", kwargs={"thread_id": thread.pk}))
        self.assertIn("Thread marked as resolved!", resolve_res.content.decode("utf-8"))

        # 3. Courses page has none of these messages
        courses_res = self.client.get(reverse("core:courses"))
        courses_content = courses_res.content.decode("utf-8")
        self.assertNotIn("Follow-up message sent.", courses_content)
        self.assertNotIn("Thread marked as resolved!", courses_content)

    # ========================================================
    # EXACTLY ONCE DISPLAY (PERSISTENCE & CONSUMPTION)
    # ========================================================

    def test_message_displays_exactly_once(self):
        """A message is consumed after its first rendering and never displays twice."""
        # 1. Login student
        res1 = self.client.post(
            reverse("core:login"),
            {"email": self.student.email, "password": self.password},
            follow=True,
        )
        self.assertEqual(res1.status_code, 200)
        content1 = res1.content.decode("utf-8")
        # Exactly one occurrence of the message in the response
        self.assertEqual(content1.count("Welcome Back!"), 1)

        # 2. Refresh dashboard -> message is consumed and must NOT appear again
        res2 = self.client.get(reverse("core:dashboard"))
        content2 = res2.content.decode("utf-8")
        self.assertNotIn("Welcome Back!", content2)
        self.assertNotIn("data-edvanto-toast", content2)

    # ========================================================
    # SECURITY & ACCESS CONTROL RESTORATION TESTS
    # ========================================================

    def test_registration_otp_verification_auto_login_and_redirects_to_dashboard(self):
        """
        Registration workflow:
        1. Student submits registration form -> OTP sent.
        2. Student verifies OTP -> automatically logged in -> redirected to dashboard.
        3. No redirect to login page, credentials not asked again.
        """
        from django.core import mail
        import re

        reg_data = {
            "full_name": "Charlie Student",
            "email": "charlie@edvanto.test",
            "phone": "+919876543210",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
            "terms": "on",
        }
        reg_res = self.client.post(reverse("core:student_register"), reg_data, follow=True)
        self.assertEqual(reg_res.status_code, 200)
        self.assertRedirects(reg_res, reverse("core:verify_otp"))
        self.assertIn("A verification code has been sent", reg_res.content.decode("utf-8"))

        # Extract 6-digit OTP from test outbox
        self.assertTrue(len(mail.outbox) > 0)
        otp_match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(otp_match)
        otp_code = otp_match.group(1)

        # Submit OTP verification
        verify_res = self.client.post(
            reverse("core:verify_otp"),
            {"otp": otp_code},
            follow=True,
        )
        self.assertEqual(verify_res.status_code, 200)
        # Direct redirect to student dashboard, NOT core:login!
        self.assertRedirects(verify_res, reverse("core:dashboard"))
        content = verify_res.content.decode("utf-8")
        self.assertIn("Registration Successful!", content)
        self.assertIn("Welcome to Edvanto! Your account has been verified successfully.", content)

        # Confirm user is authenticated without re-entering credentials
        self.assertTrue(verify_res.wsgi_request.user.is_authenticated)
        self.assertEqual(verify_res.wsgi_request.user.email, "charlie@edvanto.test")

    def test_logout_supports_both_get_and_post(self):
        """Logout must support GET and POST, destroy session, and redirect to home with success message."""
        self.client.force_login(self.student)
        # 1. GET logout
        res_get = self.client.get(reverse("core:logout"), follow=True)
        self.assertEqual(res_get.status_code, 200)
        self.assertRedirects(res_get, reverse("core:home"))
        self.assertIn("Logged Out Successfully", res_get.content.decode("utf-8"))
        self.assertIn("You have been logged out successfully. See you again!", res_get.content.decode("utf-8"))
        self.assertFalse(res_get.wsgi_request.user.is_authenticated)

        # 2. POST logout
        self.client.force_login(self.student)
        res_post = self.client.post(reverse("core:logout"), follow=True)
        self.assertEqual(res_post.status_code, 200)
        self.assertRedirects(res_post, reverse("core:home"))
        self.assertIn("Logged Out Successfully", res_post.content.decode("utf-8"))
        self.assertIn("You have been logged out successfully. See you again!", res_post.content.decode("utf-8"))
        self.assertFalse(res_post.wsgi_request.user.is_authenticated)

    def test_student_with_pending_offline_enrollment_cannot_access_learning_content(self):
        """
        A student whose offline enrollment is pending admin approval:
        1. Lands on dashboard with pending verification banner.
        2. Cannot see offline batch schedule or attendance.
        3. Cannot access course curriculum or study room.
        """
        offline_course = Course.objects.create(
            title="FullStack Offline Campus",
            slug="fullstack-offline-campus",
            mode=Course.Mode.OFFLINE,
            price=Decimal("499.00"),
            status=Course.Status.PUBLISHED,
        )
        offline_student = User.objects.create_user(
            username="offline_pending@edvanto.test",
            email="offline_pending@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
            first_name="David",
        )
        Enrollment.objects.create(
            student=offline_student,
            course=offline_course,
            payment_status=Enrollment.PaymentStatus.PENDING,
            approval_status=Enrollment.ApprovalStatus.PENDING,
        )

        self.client.force_login(offline_student)
        dash_res = self.client.get(reverse("core:dashboard"))
        self.assertEqual(dash_res.status_code, 200)
        self.assertIsNone(dash_res.context["active_enrollment"])
        self.assertIsNotNone(dash_res.context["pending_enrollment"])
        content = dash_res.content.decode("utf-8")
        self.assertIn("Enrollment Verification Pending", content)
        self.assertIn("FullStack Offline Campus", content)
        # Must NOT render offline dashboard schedule / attendance
        self.assertNotIn("Class Schedule", content)
        self.assertNotIn("Attendance Rate", content)

        # Direct access to course dashboard must be denied
        course_dash_res = self.client.get(
            reverse("core:course_dashboard", kwargs={"slug": offline_course.slug}),
            follow=True,
        )
        self.assertEqual(course_dash_res.status_code, 200)
        self.assertRedirects(course_dash_res, reverse("core:course_detail", kwargs={"slug": offline_course.slug}))
        self.assertIn("awaiting approval", course_dash_res.content.decode("utf-8"))

    def test_unenrolled_student_cannot_access_lessons_assessments_or_video(self):
        """Direct URL access to lessons, assessments, and video streaming must be denied for unenrolled users."""
        unenrolled_student = User.objects.create_user(
            username="hacker@edvanto.test",
            email="hacker@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.client.force_login(unenrolled_student)

        # 1. Lesson view blocked
        lesson_res = self.client.get(
            reverse("core:lesson", kwargs={"lesson_id": self.lesson1.pk}),
            follow=True,
        )
        self.assertEqual(lesson_res.status_code, 200)
        self.assertRedirects(lesson_res, reverse("core:dashboard"))
        self.assertIn("You are not enrolled in this course.", lesson_res.content.decode("utf-8"))

        # 2. Assessment blocked
        assessment = Assessment.objects.create(
            module=self.module,
            title="Security Test Quiz",
            is_published=True,
            pass_percentage=50,
        )
        assess_res = self.client.get(
            reverse("core:take_assessment", kwargs={"assessment_id": assessment.pk}),
            follow=True,
        )
        self.assertEqual(assess_res.status_code, 200)
        self.assertRedirects(assess_res, reverse("core:student_assessments"))
        self.assertIn("You must be enrolled in this course", assess_res.content.decode("utf-8"))

        # 3. Video streaming blocked (403 Forbidden)
        video_res = self.client.get(
            reverse("core:stream_lesson_video", kwargs={"lesson_id": self.lesson1.pk}),
        )
        self.assertEqual(video_res.status_code, 403)

    def test_student_cannot_view_other_students_doubt_threads(self):
        """A student must never be allowed to view or post on another student's doubt thread."""
        thread = DoubtThread.objects.create(
            student=self.student,
            enrollment=self.enrollment,
            lesson=self.lesson1,
            subject="Alice Private Doubt",
            status=DoubtThread.Status.OPEN,
        )
        other_student = User.objects.create_user(
            username="snooper@edvanto.test",
            email="snooper@edvanto.test",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.client.force_login(other_student)

        # Direct access to Alice's thread must return 404
        snoop_res = self.client.get(reverse("core:doubt_detail", kwargs={"thread_id": thread.pk}))
        self.assertEqual(snoop_res.status_code, 404)

    def test_invalid_otp_renders_error_on_otp_page_only(self):
        """Entering incorrect OTP shows error on OTP page and does not authenticate user."""
        reg_data = {
            "full_name": "Eve WrongOTP",
            "email": "eve@edvanto.test",
            "phone": "+919876543219",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
            "terms": "on",
        }
        self.client.post(reverse("core:student_register"), reg_data, follow=True)

        bad_otp_res = self.client.post(
            reverse("core:verify_otp"),
            {"otp": "000000"},
            follow=True,
        )
        self.assertEqual(bad_otp_res.status_code, 200)
        content = bad_otp_res.content.decode("utf-8")
        self.assertIn("Action Required", content)
        self.assertIn("Invalid OTP.", content)
        self.assertFalse(bad_otp_res.wsgi_request.user.is_authenticated)

    def test_multiple_messages_stack_in_container(self):
        """When multiple messages exist, they render and stack properly in edvantoToastContainer."""
        self.client.force_login(self.student)
        from django.contrib.messages import constants
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory
        from django.http import HttpResponse

        rf = RequestFactory()
        req = rf.get("/")
        SessionMiddleware(lambda r: None).process_request(req)
        storage = FallbackStorage(req)
        storage.add(constants.SUCCESS, "First action succeeded.", extra_tags="First Notice")
        storage.add(constants.WARNING, "Second action requires attention.", extra_tags="Second Notice")

        resp = HttpResponse()
        storage.update(resp)
        for k, v in resp.cookies.items():
            self.client.cookies[k] = v.value

        res = self.client.get(reverse("core:dashboard"))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode("utf-8")
        self.assertIn("First Notice", content)
        self.assertIn("First action succeeded.", content)
        self.assertIn("Second Notice", content)
        self.assertIn("Second action requires attention.", content)
        self.assertEqual(content.count('<h5 class="edvanto-toast-title mb-1">'), 2)

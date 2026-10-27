import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import (
    User, Course, Module, Lesson, Enrollment,
    Assessment, Question, Submission,
    DoubtThread, DoubtMessage, ConsultationBooking,
)


class SubsystemsTestCase(TestCase):
    def setUp(self):
        # Create users
        self.student = User.objects.create_user(
            username="student_user",
            email="student@example.com",
            password="Password123!",
            role=User.Role.STUDENT,
            first_name="Jane",
            last_name="Doe",
        )
        self.instructor = User.objects.create_user(
            username="instructor_user",
            email="instructor@example.com",
            password="Password123!",
            role=User.Role.INSTRUCTOR,
            first_name="John",
            last_name="Smith",
        )
        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin@example.com",
            password="Password123!",
            role=User.Role.ADMIN,
        )

        # Create Course & Curriculum
        self.course = Course.objects.create(
            title="Django Fullstack",
            slug="django-fullstack",
            instructor=self.instructor,
            mode=Course.Mode.ONLINE,
            price=Decimal("100.00"),
            status=Course.Status.PUBLISHED,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Module 1: Django Fundamentals",
            order=1,
            unlock_order=1,
        )
        self.lesson = Lesson.objects.create(
            module=self.module,
            title="Lesson 1: Introduction",
            order=1,
            unlock_order=1,
            is_published=True,
            status=Lesson.Status.PUBLISHED,
        )

        # Enroll student
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID,
            approval_status=Enrollment.ApprovalStatus.ACCEPTED,
        )

        self.client = Client()

    # ==========================================
    # 1. CAREER CONSULTATION TESTS
    # ==========================================
    def test_anonymous_cannot_request_consultation(self):
        url = reverse("core:career_consultation_request")
        response = self.client.post(url, {
            "phone": "+919876543210",
            "message": "Need advice",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ConsultationBooking.objects.count(), 0)

    def test_registered_student_can_request_consultation(self):
        self.client.force_login(self.student)
        url = reverse("core:career_consultation_request")
        response = self.client.post(
            url,
            {
                "phone": "+919876543210",
                "message": "I want to transition to backend engineering.",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")

        booking = ConsultationBooking.objects.get(email=self.student.email)
        self.assertEqual(booking.name, "Jane Doe")
        self.assertEqual(booking.phone, "+919876543210")
        self.assertEqual(booking.status, ConsultationBooking.Status.NEW)

    def test_admin_can_update_consultation_status(self):
        booking = ConsultationBooking.objects.create(
            name="Jane Doe",
            email="student@example.com",
            phone="+919876543210",
            status=ConsultationBooking.Status.NEW,
        )
        self.client.force_login(self.admin)
        url = reverse("admin_panel:consultation_update", kwargs={"booking_id": booking.pk})
        response = self.client.post(url, {
            "status": ConsultationBooking.Status.SCHEDULED,
            "assigned_to": self.instructor.pk,
            "internal_notes": "Scheduled call on Google Meet for Thursday 4 PM.",
        })
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, ConsultationBooking.Status.SCHEDULED)
        self.assertEqual(booking.assigned_to, self.instructor)
        self.assertIn("Google Meet", booking.internal_notes)

    # ==========================================
    # 2. DOUBT CLEARANCE TESTS
    # ==========================================
    def test_student_can_create_doubt_on_lesson(self):
        self.client.force_login(self.student)
        url = reverse("core:create_doubt", kwargs={"lesson_id": self.lesson.pk})
        response = self.client.post(url, {
            "subject": "Syntax error in models.py",
            "message": "Why does ForeignKey require on_delete?",
        })
        self.assertEqual(response.status_code, 302)
        thread = DoubtThread.objects.get(student=self.student, lesson=self.lesson)
        self.assertEqual(thread.subject, "Syntax error in models.py")
        self.assertEqual(thread.status, DoubtThread.Status.OPEN)
        self.assertEqual(thread.messages.count(), 1)

    def test_instructor_replies_to_doubt(self):
        thread = DoubtThread.objects.create(
            student=self.student,
            enrollment=self.enrollment,
            lesson=self.lesson,
            subject="Question on signals",
            status=DoubtThread.Status.OPEN,
        )
        DoubtMessage.objects.create(
            thread=thread,
            sender=self.student,
            message="When should post_save signal be used?",
        )

        self.client.force_login(self.admin)
        url = reverse("admin_panel:doubt_reply_admin", kwargs={"thread_id": thread.pk})
        response = self.client.post(url, {
            "message": "Use post_save when performing operations after a model is committed.",
            "mark_resolved": "false",
        })
        self.assertEqual(response.status_code, 302)
        thread.refresh_from_db()
        self.assertEqual(thread.status, DoubtThread.Status.ANSWERED)
        self.assertEqual(thread.messages.count(), 2)
        self.assertEqual(thread.assigned_instructor, self.admin)

    def test_student_can_resolve_doubt(self):
        thread = DoubtThread.objects.create(
            student=self.student,
            enrollment=self.enrollment,
            lesson=self.lesson,
            subject="Question on URL routing",
            status=DoubtThread.Status.ANSWERED,
        )
        self.client.force_login(self.student)
        url = reverse("core:doubt_resolve", kwargs={"thread_id": thread.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        thread.refresh_from_db()
        self.assertEqual(thread.status, DoubtThread.Status.RESOLVED)

    # ==========================================
    # 3. ASSESSMENT TEST SUBSYSTEM
    # ==========================================
    def test_mcq_auto_grading_and_submission(self):
        assessment = Assessment.objects.create(
            module=self.module,
            title="Django Basics Quiz",
            assessment_type=Assessment.AssessmentType.QUIZ,
            total_marks=20,
            pass_percentage=50,
            is_published=True,
            attempts_allowed=2,
        )
        q1 = Question.objects.create(
            assessment=assessment,
            question_text="What does MVT stand for?",
            question_type=Question.QuestionType.MCQ,
            options=["Model View Template", "Model View Technology", "Main View Task"],
            correct_answer="Model View Template",
            marks=10,
            order=1,
        )
        q2 = Question.objects.create(
            assessment=assessment,
            question_text="Which file defines database models?",
            question_type=Question.QuestionType.MCQ,
            options=["views.py", "models.py", "urls.py"],
            correct_answer="models.py",
            marks=10,
            order=2,
        )

        # Student submits assessment answering both correctly
        self.client.force_login(self.student)
        url = reverse("core:take_assessment", kwargs={"assessment_id": assessment.pk})
        response = self.client.post(url, {
            f"question_{q1.pk}": "Model View Template",
            f"question_{q2.pk}": "models.py",
        })
        self.assertEqual(response.status_code, 302)

        sub = Submission.objects.get(assessment=assessment, student=self.student)
        self.assertEqual(sub.status, Submission.Status.GRADED)
        self.assertEqual(sub.score, Decimal("20.00"))

        # Verify result view renders
        result_url = reverse("core:assessment_result", kwargs={"submission_id": sub.pk})
        result_resp = self.client.get(result_url)
        self.assertEqual(result_resp.status_code, 200)
        self.assertContains(result_resp, "Congratulations! You Passed")

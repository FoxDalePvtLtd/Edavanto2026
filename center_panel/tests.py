import datetime
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.center_services import (
    approve_center_application,
    record_manual_subscription_activation,
    reject_center_application,
)
from core.models import (
    Center,
    CenterApplication,
    CenterInstructor,
    CenterSubscription,
    CenterSubscriptionPlan,
    Course,
    Notification,
    OTPVerification,
    User,
)

User = get_user_model()


class CenterPanelCompleteTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin = User.objects.create_superuser(
            username="platform_admin",
            email="admin@edvanto.test",
            password="AdminPassword123!",
            role=User.Role.ADMIN,
        )

        # Center A owner & center
        self.center_a_owner = User.objects.create_user(
            username="center_a_owner",
            email="owner_a@center.test",
            password="OwnerPassword123!",
            role=User.Role.CENTER,
            first_name="Alpha",
            last_name="Owner",
        )
        self.center_a = Center.objects.create(
            name="Alpha Tech Center",
            city="Bengaluru",
            state="Karnataka",
            address="123 Tech Park",
            contact_number="+919876543210",
            email="alpha@center.test",
            owner=self.center_a_owner,
            is_active=True,
        )

        # Center B owner & center
        self.center_b_owner = User.objects.create_user(
            username="center_b_owner",
            email="owner_b@center.test",
            password="OwnerPassword123!",
            role=User.Role.CENTER,
            first_name="Beta",
            last_name="Owner",
        )
        self.center_b = Center.objects.create(
            name="Beta Tech Center",
            city="Hyderabad",
            state="Telangana",
            address="456 Cyber Gateway",
            contact_number="+919876543211",
            email="beta@center.test",
            owner=self.center_b_owner,
            is_active=True,
        )

        # Student user
        self.student = User.objects.create_user(
            username="john_student",
            email="student@edvanto.test",
            password="StudentPassword123!",
            role=User.Role.STUDENT,
        )

        # Subscription plans
        self.plan_6m = CenterSubscriptionPlan.objects.create(
            name="Semi-Annual Pro",
            duration_months=6,
            price=Decimal("15000.00"),
            is_active=True,
        )
        self.plan_1y = CenterSubscriptionPlan.objects.create(
            name="Annual Enterprise",
            duration_months=12,
            price=Decimal("25000.00"),
            is_active=True,
        )

    # -------------------------------------------------------------
    # 1 & 2. Public Center Application & Validation
    # -------------------------------------------------------------
    def test_join_as_center_page_renders(self):
        url = reverse("core:join_as_center")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Join as a Center")

    def test_join_as_center_submission_triggers_otp(self):
        url = reverse("core:join_as_center")
        payload = {
            "center_name": "Delta Learning Academy",
            "official_email": "info@deltalms.test",
            "contact_number": "+919876500001",
            "address": "Ring Road Sector 4",
            "city": "Pune",
            "state": "Maharashtra",
            "postal_code": "411001",
            "owner_name": "David Delta",
            "owner_email": "david@deltalms.test",
            "owner_phone": "+919876500002",
            "password": "DeltaPassword123!",
            "confirm_password": "DeltaPassword123!",
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("verify-otp", response.url)

        # Verify OTP record created
        otp_record = OTPVerification.objects.filter(
            identifier="david@deltalms.test",
            purpose=OTPVerification.Purpose.CENTER_REGISTRATION,
        ).first()
        self.assertIsNotNone(otp_record)
        self.assertEqual(len(otp_record.otp_code), 6)

    def test_join_as_center_rejects_duplicate_email(self):
        # Try to register using existing user's email
        url = reverse("core:join_as_center")
        payload = {
            "center_name": "Duplicate Test Center",
            "official_email": "dup@center.test",
            "contact_number": "+919876500001",
            "address": "Some Street",
            "city": "Pune",
            "state": "Maharashtra",
            "postal_code": "411001",
            "owner_name": "Alpha Duplicate",
            "owner_email": self.center_a_owner.email,  # duplicate
            "owner_phone": "+919876500099",
            "password": "Password123!",
            "confirm_password": "Password123!",
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "already exists", status_code=400)

    # -------------------------------------------------------------
    # 3 & 4. Admin Application Review & Approval / Rejection
    # -------------------------------------------------------------
    def test_admin_approves_center_application(self):
        application = CenterApplication.objects.create(
            center_name="Gamma Institute",
            official_email="contact@gamma.test",
            contact_number="+919876512345",
            address="789 Cyber Park",
            city="Chennai",
            state="Tamil Nadu",
            postal_code="600001",
            owner_name="George Gamma",
            owner_email="george@gamma.test",
            owner_phone="+919876512346",
            owner_password_hash="pbkdf2_sha256$test_dummy_hash",
            status=CenterApplication.Status.PENDING,
        )

        self.client.force_login(self.admin)
        url = reverse("admin_panel:center_application_approve", kwargs={"app_id": application.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.status, CenterApplication.Status.APPROVED)
        self.assertIsNotNone(application.center)
        self.assertEqual(application.center.name, "Gamma Institute")
        self.assertIsNotNone(application.user)
        self.assertEqual(application.user.role, User.Role.CENTER)

        # Ensure applicant received notification
        notif = Notification.objects.filter(recipient=application.user).first()
        self.assertIsNotNone(notif)
        self.assertIn("Approved", notif.title)

    def test_admin_rejects_center_application(self):
        application = CenterApplication.objects.create(
            center_name="Bogus Center",
            official_email="bogus@center.test",
            contact_number="+919876599999",
            address="Nowhere Road",
            city="Nowhere",
            state="None",
            postal_code="000000",
            owner_name="Bob Bogus",
            owner_email="bob@bogus.test",
            owner_phone="+919876599998",
            owner_password_hash="pbkdf2_sha256$test_dummy_hash",
            status=CenterApplication.Status.PENDING,
        )

        self.client.force_login(self.admin)
        url = reverse("admin_panel:center_application_reject", kwargs={"app_id": application.id})
        response = self.client.post(url, {"rejection_reason": "Missing required accreditation."})
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.status, CenterApplication.Status.REJECTED)
        self.assertEqual(application.rejection_reason, "Missing required accreditation.")

    # -------------------------------------------------------------
    # 5, 6, 7. Subscription Calendar-Month Expiry & Enforcement
    # -------------------------------------------------------------
    def test_calendar_month_calculation_6m_and_12m(self):
        sub_6m, _ = record_manual_subscription_activation(
            center=self.center_a, plan=self.plan_6m, actor=self.admin
        )
        self.assertEqual(sub_6m.end_date, sub_6m.start_date + relativedelta(months=6))

        sub_12m, _ = record_manual_subscription_activation(
            center=self.center_b, plan=self.plan_1y, actor=self.admin
        )
        self.assertEqual(sub_12m.end_date, sub_12m.start_date + relativedelta(months=12))

    def test_center_dashboard_denied_without_subscription(self):
        # Center A has no subscription yet
        self.client.force_login(self.center_a_owner)
        url = reverse("center_panel:dashboard")
        response = self.client.get(url)
        # Should redirect to subscription status or select page
        self.assertEqual(response.status_code, 302)
        self.assertIn("subscription", response.url)

    def test_center_dashboard_allowed_with_active_subscription(self):
        # Activate 6M subscription
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        self.assertTrue(self.center_a.has_active_subscription)

        self.client.force_login(self.center_a_owner)
        url = reverse("center_panel:dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Tech Center")

    def test_subscription_expiration_behavior(self):
        # Create an expired subscription
        past_start = timezone.now() - relativedelta(months=7)
        past_end = past_start + relativedelta(months=6)
        CenterSubscription.objects.create(
            center=self.center_a,
            plan=self.plan_6m,
            status=CenterSubscription.Status.EXPIRED,
            start_date=past_start,
            end_date=past_end,
        )
        self.assertFalse(self.center_a.has_active_subscription)

    # -------------------------------------------------------------
    # 8, 9, 10, 11. Center Course Workflow & Strict Approval
    # -------------------------------------------------------------
    def test_center_course_creation_starts_as_draft(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        self.client.force_login(self.center_a_owner)

        url = reverse("center_panel:course_create")
        payload = {
            "title": "Robotics with ROS2",
            "slug": "robotics-ros2",
            "description": "Comprehensive robotics masterclass.",
            "mode": Course.Mode.ONLINE,
            "level": Course.Level.INTERMEDIATE,
            "language": "English",
            "price": "4999.00",
            "discount_price": "",
            "is_free": False,
            "certificate_offered": True,
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)

        course = Course.objects.get(slug="robotics-ros2")
        self.assertEqual(course.center, self.center_a)
        self.assertEqual(course.approval_status, Course.ApprovalStatus.DRAFT)
        self.assertFalse(course.is_published)

    def test_center_cannot_publish_unapproved_course(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        course = Course.objects.create(
            title="AI Vision",
            slug="ai-vision",
            center=self.center_a,
            approval_status=Course.ApprovalStatus.DRAFT,
            status=Course.Status.DRAFT,
            price=Decimal("2999.00"),
        )

        self.client.force_login(self.center_a_owner)
        edit_url = reverse("center_panel:course_edit", kwargs={"course_id": course.id})
        response = self.client.post(edit_url, {
            "title": course.title,
            "slug": course.slug,
            "mode": Course.Mode.ONLINE,
            "level": Course.Level.BEGINNER,
            "language": "English",
            "price": "2999.00",
            "action": "publish",
        })
        self.assertEqual(response.status_code, 302)

        course.refresh_from_db()
        self.assertFalse(course.is_published)
        self.assertEqual(course.approval_status, Course.ApprovalStatus.DRAFT)

    def test_admin_approves_course_and_center_can_publish(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        course = Course.objects.create(
            title="Embedded IoT",
            slug="embedded-iot",
            center=self.center_a,
            approval_status=Course.ApprovalStatus.PENDING,
            status=Course.Status.DRAFT,
            price=Decimal("1999.00"),
        )

        # Admin approves course
        self.client.force_login(self.admin)
        admin_url = reverse("admin_panel:center_course_review", kwargs={"course_id": course.id})
        response = self.client.post(admin_url, {"action": "approve"})
        self.assertEqual(response.status_code, 302)

        course.refresh_from_db()
        self.assertEqual(course.approval_status, Course.ApprovalStatus.APPROVED)
        self.assertEqual(course.approved_by, self.admin)

        # Center publishes approved course
        self.client.force_login(self.center_a_owner)
        publish_url = reverse("center_panel:course_edit", kwargs={"course_id": course.id})
        response = self.client.post(publish_url, {
            "title": course.title,
            "slug": course.slug,
            "mode": Course.Mode.ONLINE,
            "level": Course.Level.BEGINNER,
            "language": "English",
            "price": "1999.00",
            "action": "publish",
        })
        self.assertEqual(response.status_code, 302)

        course.refresh_from_db()
        self.assertTrue(course.is_published)

    # -------------------------------------------------------------
    # 12 & 13. Center Instructor Creation and Assignment
    # -------------------------------------------------------------
    def test_center_onboards_instructor_and_assigns_to_course(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        self.client.force_login(self.center_a_owner)

        # Onboard Instructor
        url = reverse("center_panel:instructor_add")
        payload = {
            "first_name": "Rohan",
            "last_name": "Verma",
            "email": "rohan.instructor@alpha.test",
            "phone": "+919876543299",
            "designation": "Senior Robotics Specialist",
            "password": "InstructorPass123!",
            "confirm_password": "InstructorPass123!",
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)

        instructor_user = User.objects.get(email="rohan.instructor@alpha.test")
        self.assertEqual(instructor_user.role, User.Role.INSTRUCTOR)

        link = CenterInstructor.objects.filter(center=self.center_a, instructor=instructor_user).first()
        self.assertIsNotNone(link)
        self.assertEqual(link.designation, "Senior Robotics Specialist")

        # Assign to Center Course
        course = Course.objects.create(
            title="Microcontroller Programming",
            slug="mcu-programming",
            center=self.center_a,
            approval_status=Course.ApprovalStatus.APPROVED,
            price=Decimal("1500.00"),
        )
        edit_url = reverse("center_panel:course_edit", kwargs={"course_id": course.id})
        post_data = {
            "title": course.title,
            "slug": course.slug,
            "instructor": instructor_user.id,
            "mode": Course.Mode.ONLINE,
            "level": Course.Level.BEGINNER,
            "language": "English",
            "price": "1500.00",
            "discount_price": "",
            "is_free": False,
            "certificate_offered": True,
        }
        resp = self.client.post(edit_url, post_data)
        self.assertEqual(resp.status_code, 302)

        course.refresh_from_db()
        self.assertEqual(course.instructor, instructor_user)

    # -------------------------------------------------------------
    # 16. Strict Permission Isolation
    # -------------------------------------------------------------
    def test_center_isolation_cannot_view_or_edit_other_center_course(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        record_manual_subscription_activation(center=self.center_b, plan=self.plan_6m, actor=self.admin)

        course_b = Course.objects.create(
            title="Beta Autonomous Driving",
            slug="beta-autonomous",
            center=self.center_b,
            price=Decimal("9999.00"),
        )

        # Center A owner attempts to edit Center B course
        self.client.force_login(self.center_a_owner)
        edit_url = reverse("center_panel:course_edit", kwargs={"course_id": course_b.id})
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 404)

    def test_student_cannot_access_center_panel(self):
        self.client.force_login(self.student)
        url = reverse("center_panel:dashboard")
        response = self.client.get(url)
        # Should redirect to home with forbidden message
        self.assertEqual(response.status_code, 302)

    def test_suspended_center_cannot_access_dashboard(self):
        record_manual_subscription_activation(center=self.center_a, plan=self.plan_6m, actor=self.admin)
        self.center_a.is_suspended = True
        self.center_a.save()

        self.client.force_login(self.center_a_owner)
        url = reverse("center_panel:dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:home"))

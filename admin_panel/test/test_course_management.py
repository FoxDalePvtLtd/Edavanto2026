from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from core.models import Course, User, Center


class CourseManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="course-admin", email="course-admin@example.test", password="Strong-admin-pass-123!"
        )
        cls.instructor = User.objects.create_user(
            username="instructor", email="instructor@example.test", password="Strong-instructor-pass-123!",
            role=User.Role.INSTRUCTOR, first_name="Course", last_name="Instructor", is_active=True
        )
        cls.center = Center.objects.create(name="Test Center", is_active=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        data = {
            "title": "Django Fundamentals", "slug": "django-fundamentals",
            "description": "A complete introduction to Django.", "category": Course.Category.DEVELOPMENT,
            "mode": Course.Mode.ONLINE, "instructor": str(self.instructor.pk), "center": "",
            "price": "1000.00", "discounted_price": "800.00", "duration_hours": "24",
            "duration_weeks": "", "requires_instructor_approval": "",
        }
        data.update(overrides)
        return data

    def test_course_list_uses_database_and_filters(self):
        Course.objects.create(title="Django Fundamentals", slug="django-fundamentals", description="Django", category=Course.Category.DEVELOPMENT, mode=Course.Mode.ONLINE, price=Decimal("1000"), status=Course.Status.DRAFT)
        Course.objects.create(title="Excel Basics", slug="excel-basics", description="Excel", category=Course.Category.BUSINESS, mode=Course.Mode.OFFLINE, price=Decimal("500"), center=self.center, status=Course.Status.PUBLISHED)
        response = self.client.get(reverse("admin_panel:course_dashboard"), {"q": "Django", "status": "draft"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django Fundamentals")
        self.assertNotContains(response, "Excel Basics")

    def test_create_course_save_draft(self):
        response = self.client.post(reverse("admin_panel:course_create"), self.payload(), follow=True)
        self.assertRedirects(response, reverse("admin_panel:course_dashboard"))
        course = Course.objects.get(slug="django-fundamentals")
        self.assertEqual(course.status, Course.Status.DRAFT)
        self.assertEqual(course.duration_hours, 24)

    def test_create_course_publish_only_on_explicit_publish_action(self):
        response = self.client.post(reverse("admin_panel:course_create"), self.payload(action="publish"), follow=True)
        self.assertRedirects(response, reverse("admin_panel:course_dashboard"))
        self.assertEqual(Course.objects.get(slug="django-fundamentals").status, Course.Status.PUBLISHED)

    def test_save_continue_preserves_existing_published_status(self):
        course = Course.objects.create(title="Existing Course", slug="existing-course", description="Details", mode=Course.Mode.ONLINE, price=Decimal("100"), status=Course.Status.PUBLISHED)
        data = self.payload(title="Existing Course", slug="existing-course", action="save_continue")
        response = self.client.post(reverse("admin_panel:course_form", kwargs={"course_id": course.pk}), data)
        self.assertRedirects(response, reverse("admin_panel:course_form", kwargs={"course_id": course.pk}))
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.PUBLISHED)

    def test_invalid_discount_is_rejected(self):
        response = self.client.post(reverse("admin_panel:course_create"), self.payload(discounted_price="1200.00"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(slug="django-fundamentals").exists())
        self.assertContains(response, "Discounted price cannot be greater than the course price.")

    def test_offline_course_requires_center(self):
        response = self.client.post(reverse("admin_panel:course_create"), self.payload(mode=Course.Mode.OFFLINE, center="", duration_hours="", duration_weeks="8"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(slug="django-fundamentals").exists())
        self.assertContains(response, "A center is required for an offline course.")

    def test_save_continue_does_not_publish_new_course(self):
        response = self.client.post(reverse("admin_panel:course_create"), self.payload(action="save_continue"))
        course = Course.objects.get(slug="django-fundamentals")
        self.assertRedirects(response, reverse("admin_panel:course_form", kwargs={"course_id": course.pk}))
        self.assertEqual(course.status, Course.Status.DRAFT)

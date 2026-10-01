
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from admin_panel import views


@override_settings(LOGIN_URL="/accounts/login/")
class AdminAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def make_user(*, active=True, superuser=False):
        return SimpleNamespace(
            is_authenticated=True,
            is_active=active,
            is_superuser=superuser,
        )

    def test_anonymous_html_request_redirects_to_login(self):
        request = self.factory.get("/control/")
        request.user = AnonymousUser()

        response = views.dashboard(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_student_cannot_access_dashboard(self):
        request = self.factory.get("/control/")
        request.user = self.make_user()

        response = views.dashboard(request)

        self.assertEqual(response.status_code, 403)

    def test_ordinary_staff_without_superuser_privilege_is_denied(self):
        # This account represents staff without admin-panel authorization.
        request = self.factory.get("/control/")
        request.user = self.make_user()

        response = views.dashboard(request)

        self.assertEqual(response.status_code, 403)

    def test_inactive_superuser_is_denied(self):
        request = self.factory.get("/control/")
        request.user = self.make_user(active=False, superuser=True)

        response = views.dashboard(request)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_json_request_returns_401(self):
        request = self.factory.get(
            "/control/",
            HTTP_ACCEPT="application/json",
        )
        request.user = AnonymousUser()

        response = views.dashboard(request)

        self.assertEqual(response.status_code, 401)

    def test_student_post_cannot_create_or_publish_course(self):
        request = self.factory.post(
            "/control/courses/new/",
            {"action": "publish"},
        )
        request.user = self.make_user()

        with patch("admin_panel.views.CourseAdminForm") as form_class:
            response = views.course_form(request)

        self.assertEqual(response.status_code, 403)
        form_class.assert_not_called()

    def test_authorized_superuser_can_reach_dashboard(self):
        request = self.factory.get("/control/")
        request.user = self.make_user(superuser=True)

        with patch(
            "admin_panel.views.render",
            return_value=HttpResponse("Dashboard"),
        ):
            response = views.dashboard(request)

        self.assertEqual(response.status_code, 200)

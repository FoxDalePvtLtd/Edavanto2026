from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from unittest.mock import patch

from core.models import User
from admin_panel.forms import UserAdminCreateForm, UserAdminUpdateForm
from admin_panel import views


class UserAdminFormTests(TestCase):
    def test_create_form_hashes_password_and_never_grants_privileges(self):
        form = UserAdminCreateForm(data={
            "first_name": "New",
            "last_name": "Student",
            "email": "newstudent@example.test",
            "phone": "1234567890",
            "role": User.Role.STUDENT,
            "bio": "",
            "password1": "A-long-test-password-923!",
            "password2": "A-long-test-password-923!",
            "is_superuser": "on",
            "is_staff": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.check_password("A-long-test-password-923!"))
        self.assertEqual(user.username, "newstudent@example.test")
        self.assertEqual(user.email, "newstudent@example.test")
        from django.contrib.auth import authenticate
        self.assertEqual(
            authenticate(username="newstudent@example.test", password="A-long-test-password-923!"),
            user,
        )
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.is_active)
        self.assertNotIn(User.Role.ADMIN, dict(form.fields["role"].choices))

    def test_create_form_rejects_mismatched_passwords(self):
        form = UserAdminCreateForm(data={
            "first_name": "Another",
            "last_name": "Student",
            "email": "another@example.test",
            "phone": "",
            "role": User.Role.STUDENT,
            "bio": "",
            "password1": "A-long-test-password-923!",
            "password2": "Different-password-123!",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)


    def test_create_form_requires_valid_email_and_first_name(self):
        base_data = {
            "first_name": "   ",
            "last_name": "Student",
            "email": "not-an-email",
            "phone": "",
            "role": User.Role.STUDENT,
            "bio": "",
            "password1": "A-long-test-password-923!",
            "password2": "A-long-test-password-923!",
        }
        form = UserAdminCreateForm(data=base_data)
        self.assertFalse(form.is_valid())
        self.assertIn("first_name", form.errors)
        self.assertIn("email", form.errors)

    def test_create_form_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="existing@example.test",
            email="existing@example.test",
            password="Existing-user-pass-123!",
        )
        form = UserAdminCreateForm(data={
            "first_name": "New",
            "last_name": "Student",
            "email": "EXISTING@example.test",
            "phone": "",
            "role": User.Role.STUDENT,
            "bio": "",
            "password1": "A-long-test-password-923!",
            "password2": "A-long-test-password-923!",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_update_form_does_not_expose_privilege_fields_or_password(self):
        user = User.objects.create_user(username="editable", password="Initial-pass-123!")
        form = UserAdminUpdateForm(instance=user)
        self.assertNotIn("username", form.fields)
        for forbidden in ("password", "is_superuser", "is_staff", "groups", "user_permissions", "is_active"):
            self.assertNotIn(forbidden, form.fields)


class UserAdminActionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser(
            username="siteadmin", email="admin@example.test", password="Strong-admin-pass-123!"
        )

    def _request_with_messages(self, path, target_user):
        request = self.factory.post(path)
        request.user = self.admin
        setattr(request, "session", {})
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_toggle_active_uses_post_and_updates_managed_user(self):
        managed = User.objects.create_user(username="managed", password="Strong-user-pass-123!")
        request = self._request_with_messages("/admin-panel/users/", managed)
        response = views.user_toggle_active(request, managed.pk)
        managed.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(managed.is_active)

    def test_cannot_deactivate_current_admin_account(self):
        request = self._request_with_messages("/admin-panel/users/", self.admin)
        with patch("admin_panel.views.redirect", return_value=HttpResponse(status=302)):
            response = views.user_toggle_active(request, self.admin.pk)
        self.admin.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.admin.is_active)


from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse


def _is_json_request(request):
    """Detect AJAX or clients explicitly requesting JSON."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _is_authorized_admin(user):
    """
    Conservative initial policy:
    only active superusers can access the admin panel.

    This intentionally fails closed for custom user models that do not
    expose Django's is_superuser field.
    """
    return (
        user.is_authenticated
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )


def admin_required(view_func):
    """
    Protect an administrative view at the server level.

    Anonymous HTML requests: redirect to the configured login page.
    Anonymous AJAX/JSON requests: HTTP 401.
    Authenticated unauthorized requests: HTTP 403.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if _is_json_request(request):
                return JsonResponse(
                    {"detail": "Authentication required."},
                    status=401,
                )

            return redirect_to_login(
                request.get_full_path(),
                login_url=settings.LOGIN_URL,
            )

        if not _is_authorized_admin(request.user):
            if _is_json_request(request):
                return JsonResponse(
                    {"detail": "Permission denied."},
                    status=403,
                )

            return HttpResponseForbidden("Permission denied.")

        return view_func(request, *args, **kwargs)

    return wrapper

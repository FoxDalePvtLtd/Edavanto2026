from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from core.models import CenterInstructor, User


def _is_json_request(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def instructor_required(view_func=None):
    """
    Decorator for views that strictly require an authenticated Instructor.
    - User must be authenticated and active.
    - User role must be INSTRUCTOR (or superuser).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Authentication required."}, status=401)
                return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

            user = request.user
            if not user.is_active:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Account inactive."}, status=403)
                return HttpResponseForbidden("Your account is inactive.")

            if user.role != User.Role.INSTRUCTOR and not user.is_superuser:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Instructor access required."}, status=403)
                messages.error(request, "Access restricted to instructors only.")
                return redirect("core:home")

            # Check if instructor is linked to a center and if that center is suspended
            center_link = (
                CenterInstructor.objects.filter(instructor=user, is_active=True)
                .select_related("center")
                .first()
            )
            if center_link and center_link.center.is_suspended:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Associated center is suspended."}, status=403)
                messages.error(
                    request,
                    "The center associated with your instructor account has been suspended. Please contact your center administrator.",
                )
                return redirect("core:home")

            request.center_link = center_link
            request.center = center_link.center if center_link else None

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator

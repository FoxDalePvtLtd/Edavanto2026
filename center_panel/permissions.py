from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from core.models import Center, User


def _is_json_request(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def center_required(view_func=None, *, require_subscription=True):
    """
    Decorator for views that strictly require an authenticated Center owner.
    - User must be authenticated and active.
    - User must own or be associated with an active, non-suspended Center.
    - If require_subscription=True: center must have an active subscription.
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

            # Superusers can inspect centers if needed, but standard center users are owners
            center = getattr(user, "managed_center", None)
            if not center:
                center = Center.objects.filter(owner=user).first()

            if not center and user.is_superuser:
                # If superuser visits without center, fallback to first center or redirect
                center = Center.objects.first()

            if not center:
                if _is_json_request(request):
                    return JsonResponse({"detail": "No registered center found."}, status=403)
                messages.error(request, "You do not have a registered center associated with your account.")
                return redirect("core:home")

            if center.is_suspended:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Center suspended."}, status=403)
                messages.error(request, "Your center account has been suspended. Please contact Edvanto administration.")
                return redirect("core:home")

            # Attach center to request for convenience
            request.center = center
            request.subscription = center.get_active_subscription()

            if require_subscription and not center.has_active_subscription:
                if _is_json_request(request):
                    return JsonResponse({"detail": "Active subscription required."}, status=402)
                messages.warning(
                    request,
                    "An active subscription is required to access center management features. Please choose or renew your plan.",
                )
                return redirect("center_panel:subscription_status")

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator

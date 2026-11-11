# core/context_processors.py
from core.models import Notification

def admin_notification_context(request):
    if request.user.is_authenticated and request.user.is_staff:
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return {
            "admin_unread_notifications_count": unread_count,
        }
    return {}
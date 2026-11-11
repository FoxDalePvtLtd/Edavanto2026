from core.models import Notification

def admin_notifications(request):
    if request.user.is_authenticated and request.user.role in ['instructor', 'admin', 'staff']:
        notifications = Notification.objects.filter(
            recipient=request.user
        ).order_by('-created_at')
        
        unread_count = notifications.filter(is_read=False).count()
        
        return {
            "admin_notifications": notifications,
            "admin_unread_count": unread_count,
        }
    return {}

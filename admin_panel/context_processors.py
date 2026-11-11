from core.models import Notification

def admin_notifications(request):
    if request.user.is_authenticated and request.user.role in ['instructor', 'admin', 'staff']:
        # Base query for the logged-in user
        user_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
        
        # Calculate unread count directly from the model manager / separate query
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        
        # Sliced notifications for the modal dropdown display
        notifications = user_notifications[:10]
        
        return {
            "admin_notifications": notifications,
            "admin_unread_count": unread_count,
        }
    return {}
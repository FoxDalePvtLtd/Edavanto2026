from django import template
from core.models import Notification

register = template.Library()

@register.inclusion_tag('admin/notifications_panel.html', takes_context=True)
def render_admin_notifications(context):
    request = context['request']
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")[:10]
        unread_count = notifications.filter(is_read=False).count()
    else:
        notifications = []
        unread_count = 0

    return{
        'notifications': notifications,
        'unread_count': unread_count,
        'request': request,
    }
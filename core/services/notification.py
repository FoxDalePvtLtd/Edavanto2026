from django.utils import timezone
from core.models import Notification, NotificationDelivery

def create_admin_notification(recipient, title, message, n_type=Notification.NotificationType.SYSTEM):
    """Helper functon to create a notification and queue its delivery channels."""
    notification = Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=n_type,
        is_read = False,
    )


    # Create an in-app delivery tracker record 
    NotificationDelivery.objects.create(
        notification=notification,
        channel=NotificationDelivery.Channel.IN_APP,
        status=NotificationDelivery.Status.SENT,
        sent_at=timezone.now()
    )

    return notification
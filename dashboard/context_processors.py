from django.db.models import Q
from emails.models import Email, EmailCategory, PrioritySender
from notifications.models import Notification
from ai_engine.constants import EMAIL_CATEGORIES, PRIMARY_CATEGORIES, CATEGORY_META


def global_ui_context(request):
    """
    Context processor supplying badge counters, active states, and user profile data
    globally to layout templates without redundant database hits.
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'global_unread_emails': 0,
            'global_important_emails': 0,
            'global_unread_notifications': 0,
            'recent_notifications': [],
            'all_categories': PRIMARY_CATEGORIES,
            'category_meta': CATEGORY_META,
        }

    unread_emails = Email.objects.filter(user=request.user, is_read=False).count()

    important_sender_emails = list(
        PrioritySender.objects.filter(user=request.user, is_important=True).values_list('email_address', flat=True)
    )

    important_emails = Email.objects.filter(
        user=request.user
    ).filter(
        Q(user_is_important=True) |
        (
            Q(user_is_important__isnull=True) & (
                Q(is_pinned=True) |
                Q(ai_is_important=True) |
                Q(gmail_is_important=True) |
                Q(is_important=True) |
                Q(sender_email__in=important_sender_emails)
            )
        )
    ).count()

    unread_notifs = Notification.objects.filter(user=request.user, is_read=False).count()
    recent_notifs = Notification.objects.filter(user=request.user).order_by('-created_at')[:5]

    from django.conf import settings
    from notifications.models import NotificationPreference
    user_pref = NotificationPreference.get_for_user(request.user)

    return {
        'global_unread_emails': unread_emails,
        'global_important_emails': important_emails,
        'global_unread_notifications': unread_notifs,
        'recent_notifications': recent_notifs,
        'all_categories': PRIMARY_CATEGORIES,
        'category_meta': CATEGORY_META,
        'user_notif_pref': user_pref,
        'vapid_public_key': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        'web_push_enabled': getattr(settings, 'WEB_PUSH_ENABLED', False),
        'websocket_enabled': getattr(settings, 'WEBSOCKET_ENABLED', True),
        'notification_poll_interval': getattr(settings, 'NOTIFICATION_POLL_INTERVAL', 30),
    }

"""
Notification Engine Services for Phase 6.
Handles effective importance evaluation, deterministic notification creation,
deduplication, Channels WebSocket broadcast, Web Push dispatch, and status management.
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.utils.html import strip_tags
import bleach

from .models import Notification, NotificationPreference, PushSubscription
from emails.models import Email, PrioritySender

logger = logging.getLogger(__name__)


def sanitize_text(text: str, max_chars: int) -> str:
    """Strips all HTML tags and collapses spaces to prevent XSS in notifications."""
    if not text:
        return ''
    cleaned = bleach.clean(strip_tags(text), tags=[], strip=True).strip()
    # Normalize whitespaces
    cleaned = ' '.join(cleaned.split())
    return cleaned[:max_chars]


def get_effective_notification_source(email: Email, preference: NotificationPreference = None):
    """
    Evaluates whether an email warrants a notification based on the Phase 5 importance
    hierarchy and user notification preferences.
    
    Returns tuple: (should_notify: bool, notif_type: str, importance_source: str, sender_display: str)
    """
    if not email or not email.user_id:
        return False, None, None, None

    pref = preference or NotificationPreference.get_for_user(email.user)

    # 1. Global important email toggle check
    if not pref.important_email_enabled:
        return False, None, None, None

    sender_email_normalized = (email.sender_email or '').strip().lower()

    # 2. Priority Sender Rule (Takes priority for fast notification)
    priority_sender = PrioritySender.objects.filter(
        user=email.user,
        email_address=sender_email_normalized
    ).first()

    if priority_sender and priority_sender.is_important:
        if priority_sender.notification_enabled and pref.important_sender_enabled:
            display_name = priority_sender.display_name or email.sender_name or email.sender_email
            return True, Notification.TYPE_IMPORTANT_SENDER, Notification.SOURCE_IMPORTANT_SENDER, display_name

    # 3. User explicit override
    if email.user_is_important is True:
        display_name = email.effective_sender_name
        return True, Notification.TYPE_USER_IMPORTANT, Notification.SOURCE_USER_OVERRIDE, display_name
    elif email.user_is_important is False:
        # User explicitly flagged NOT important; suppress notification
        return False, None, None, None

    # 4. Pinned email (if enabled in user preferences)
    if email.is_pinned and pref.notify_pinned_enabled:
        return True, Notification.TYPE_IMPORTANT_EMAIL, Notification.SOURCE_PINNED, email.effective_sender_name

    # 5. AI Classified as Important
    if email.ai_is_important is True:
        if pref.ai_important_enabled:
            return True, Notification.TYPE_AI_IMPORTANT, Notification.SOURCE_AI, email.effective_sender_name

    # 6. Gmail IMPORTANT label (only if preference allows)
    if email.gmail_is_important and pref.gmail_important_enabled:
        return True, Notification.TYPE_IMPORTANT_EMAIL, Notification.SOURCE_GMAIL, email.effective_sender_name

    return False, None, None, None


def create_important_notification(email: Email, force_source: str = None) -> Notification | None:
    """
    Creates a Notification record for an important email if not already created.
    Guarantees strict duplicate prevention via deterministic deduplication_key.
    Dispatches real-time WebSocket and mobile Web Push events upon creation.
    """
    if not email or not email.user:
        return None

    pref = NotificationPreference.get_for_user(email.user)
    should_notify, notif_type, importance_source, sender_display = get_effective_notification_source(email, pref)

    if force_source:
        should_notify = True
        importance_source = force_source
        if force_source == Notification.SOURCE_AI:
            notif_type = Notification.TYPE_AI_IMPORTANT
        elif force_source == Notification.SOURCE_IMPORTANT_SENDER:
            notif_type = Notification.TYPE_IMPORTANT_SENDER
        elif force_source == Notification.SOURCE_USER_OVERRIDE:
            notif_type = Notification.TYPE_USER_IMPORTANT
        else:
            notif_type = Notification.TYPE_IMPORTANT_EMAIL
        sender_display = email.effective_sender_name

    if not should_notify:
        return None

    # Deterministic deduplication key for this email and event
    dedup_key = f"important_email_{email.id}"

    # Check if a notification already exists
    existing = Notification.objects.filter(deduplication_key=dedup_key).first()
    if existing:
        logger.debug("Notification for email id=%s already exists (dedup_key=%s). Skipping duplicate.", email.id, dedup_key)
        return existing

    # Format Title <= 100 characters using effective sender name
    title = sanitize_text(sender_display, 100) or 'Important Email'

    # Format Message <= 250 characters with subject snippet
    subject_clean = sanitize_text(email.subject or '(No Subject)', 180)
    if importance_source == Notification.SOURCE_IMPORTANT_SENDER:
        message = f"Important email received: {subject_clean}"
    elif importance_source == Notification.SOURCE_AI:
        message = f"AI detected an important email: {subject_clean}"
    elif importance_source == Notification.SOURCE_USER_OVERRIDE:
        message = f"Important email flagged by you: {subject_clean}"
    elif importance_source == Notification.SOURCE_PINNED:
        message = f"Pinned email alert: {subject_clean}"
    else:
        message = f"Important email received: {subject_clean}"

    message = sanitize_text(message, 250)
    action_url = f"/inbox/{email.id}/"

    try:
        notification = Notification.objects.create(
            user=email.user,
            email=email,
            title=title,
            message=message,
            notification_type=notif_type,
            importance_source=importance_source,
            priority=Notification.PRIORITY_HIGH,
            action_url=action_url,
            deduplication_key=dedup_key,
        )
    except Exception as exc:
        # Handle rare race condition where unique constraint on dedup_key catches concurrent creation
        logger.warning("Duplicate notification caught by constraint for email %s: %s", email.id, exc)
        return Notification.objects.filter(deduplication_key=dedup_key).first()

    logger.info("Created notification id=%s [%s] for user %s: %s", notification.id, importance_source, email.user.email, title)

    # Dispatch Real-time Broadcast
    try:
        broadcast_notification_event(notification)
    except Exception as exc:
        logger.error("Failed to broadcast notification event id=%s: %s", notification.id, exc)

    # Dispatch Mobile Push if enabled
    if pref.push_enabled:
        try:
            send_push_notification(notification)
        except Exception as exc:
            logger.error("Failed to dispatch push notification id=%s: %s", notification.id, exc)

    return notification


def broadcast_notification_event(notification: Notification):
    """
    Pushes real-time notification payload to the user's private Channels group.
    """
    if not getattr(settings, 'WEBSOCKET_ENABLED', True):
        return

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        group_name = f"user_{notification.user.id}_notifications"
        unread_count = Notification.objects.filter(user=notification.user, is_read=False).count()

        payload = {
            "type": "notification_message",
            "notification_id": notification.id,
            "email_id": notification.email_id,
            "title": notification.title,
            "message": notification.message,
            "url": notification.action_url or '/notifications/',
            "notification_type": notification.notification_type,
            "importance_source": notification.importance_source,
            "priority": notification.priority,
            "icon_class": notification.icon_class,
            "badge_class": notification.badge_class,
            "created_at": notification.created_at.strftime('%H:%M'),
            "unread_count": unread_count,
        }

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "notification.broadcast",
                "data": payload
            }
        )
        notification.delivered_browser = True
        notification.save(update_fields=['delivered_browser'])
    except Exception as exc:
        logger.debug("WebSocket broadcast skipped or unavailable: %s", exc)


def send_push_notification(notification: Notification):
    """
    Dispatches Web Push notification payload to subscribed user devices using pywebpush.
    Automatically prunes expired/invalid push subscriptions (HTTP 404/410).
    """
    if not getattr(settings, 'WEB_PUSH_ENABLED', False):
        return

    vapid_private_key = getattr(settings, 'VAPID_PRIVATE_KEY', '')
    vapid_claims_email = getattr(settings, 'VAPID_CLAIMS_EMAIL', 'admin@smartmail.ai')

    if not vapid_private_key:
        logger.debug("Web Push enabled but VAPID_PRIVATE_KEY is empty. Skipping.")
        return

    import json
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush is not installed. Web push skipped.")
        return

    subscriptions = PushSubscription.objects.filter(user=notification.user)
    if not subscriptions.exists():
        return

    payload_json = json.dumps({
        'title': notification.title,
        'body': notification.message,
        'icon': '/static/images/logo-192.png',
        'badge': '/static/images/badge-72.png',
        'data': {
            'url': notification.action_url or '/inbox/',
            'notification_id': notification.id,
            'email_id': notification.email_id
        }
    })

    vapid_claims = {
        'sub': f'mailto:{vapid_claims_email}'
    }

    delivered_any = False
    for sub in subscriptions:
        subscription_info = {
            'endpoint': sub.endpoint,
            'keys': {
                'p256dh': sub.p256dh,
                'auth': sub.auth
            }
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload_json,
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims
            )
            delivered_any = True
        except WebPushException as exc:
            logger.warning("WebPush error for endpoint %s: %s", sub.endpoint[:30], exc)
            # 404 Not Found or 410 Gone indicates the browser unregistered the subscription
            if exc.response is not None and exc.response.status_code in (404, 410):
                logger.info("Pruning expired push subscription id=%s", sub.id)
                sub.delete()
        except Exception as exc:
            logger.warning("Unexpected error during push delivery: %s", exc)

    if delivered_any:
        notification.delivered_push = True
        notification.save(update_fields=['delivered_push'])


def mark_notification_read(notification_id: int, user) -> bool:
    """Marks a single notification as read if owned by the user."""
    notif = Notification.objects.filter(id=notification_id, user=user).first()
    if notif:
        notif.is_read = True
        notif.read_at = timezone.now()
        notif.save(update_fields=['is_read', 'read_at'])
        return True
    return False


def mark_all_read(user) -> int:
    """Marks all unread notifications for the user as read."""
    now = timezone.now()
    count = Notification.objects.filter(user=user, is_read=False).update(is_read=True, read_at=now)
    return count


def delete_notification(notification_id: int, user) -> bool:
    """
    Safely deletes a notification record for a user.
    CRITICAL: Deleting a notification NEVER deletes the associated Email object.
    """
    notif = Notification.objects.filter(id=notification_id, user=user).first()
    if notif:
        notif.delete()
        return True
    return False


def get_unread_count(user) -> int:
    """Returns total unread notifications count for the user."""
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(user=user, is_read=False).count()


def create_test_notification(user) -> Notification:
    """
    Generates an explicit test notification for the user to verify real-time alerts.
    Clearly labeled so as not to confuse users with real email activity.
    """
    title = "SmartMail Test Alert"
    message = "This is a test notification to verify your real-time desktop and in-app alerts."
    dedup_key = f"test_notif_{user.id}_{int(timezone.now().timestamp())}"

    notif = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.TYPE_SYSTEM,
        importance_source=Notification.SOURCE_SYSTEM,
        priority=Notification.PRIORITY_MEDIUM,
        action_url="/notifications/",
        deduplication_key=dedup_key,
    )
    broadcast_notification_event(notif)
    return notif


def cleanup_old_notifications(days: int = None) -> int:
    """
    Cleans up notification records older than NOTIFICATION_RETENTION_DAYS.
    Does NOT affect underlying Email records.
    """
    retention_days = days or getattr(settings, 'NOTIFICATION_RETENTION_DAYS', 90)
    cutoff = timezone.now() - timedelta(days=retention_days)
    count, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
    logger.info("Cleaned up %d old notifications prior to %s", count, cutoff)
    return count

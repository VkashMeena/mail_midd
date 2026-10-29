import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone

from .models import Notification, NotificationPreference, PushSubscription
from .services import (
    mark_notification_read,
    mark_all_read,
    delete_notification,
    get_unread_count,
    create_test_notification
)


@login_required
def notifications_view(request):
    """
    Notification Center displaying real-time and historical alerts.
    Supports tab filtering (All, Unread, Important, Senders, AI) and full-text search.
    """
    tab = request.GET.get('tab', 'all')
    search_query = request.GET.get('q', '').strip()

    base_qs = Notification.objects.filter(user=request.user)

    if search_query:
        base_qs = base_qs.filter(
            Q(title__icontains=search_query) |
            Q(message__icontains=search_query) |
            Q(email__subject__icontains=search_query) |
            Q(email__sender_name__icontains=search_query) |
            Q(email__sender_email__icontains=search_query)
        )

    if tab == 'unread':
        qs = base_qs.filter(is_read=False)
    elif tab == 'important':
        qs = base_qs.filter(
            Q(priority=Notification.PRIORITY_HIGH) |
            Q(notification_type__in=[
                Notification.TYPE_IMPORTANT_EMAIL,
                Notification.TYPE_IMPORTANT_SENDER,
                Notification.TYPE_AI_IMPORTANT,
                Notification.TYPE_USER_IMPORTANT
            ])
        )
    elif tab == 'senders':
        qs = base_qs.filter(
            Q(notification_type=Notification.TYPE_IMPORTANT_SENDER) |
            Q(importance_source=Notification.SOURCE_IMPORTANT_SENDER)
        )
    elif tab == 'ai':
        qs = base_qs.filter(
            Q(notification_type=Notification.TYPE_AI_IMPORTANT) |
            Q(importance_source=Notification.SOURCE_AI)
        )
    else:
        qs = base_qs

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    user_all_qs = Notification.objects.filter(user=request.user)

    context = {
        'page_title': 'Notification Center',
        'notifications': page_obj,
        'page_obj': page_obj,
        'current_tab': tab,
        'search_query': search_query,
        'all_count': user_all_qs.count(),
        'unread_count': user_all_qs.filter(is_read=False).count(),
        'important_count': user_all_qs.filter(
            Q(priority=Notification.PRIORITY_HIGH) |
            Q(notification_type__in=[
                Notification.TYPE_IMPORTANT_EMAIL,
                Notification.TYPE_IMPORTANT_SENDER,
                Notification.TYPE_AI_IMPORTANT,
                Notification.TYPE_USER_IMPORTANT
            ])
        ).count(),
        'sender_count': user_all_qs.filter(
            Q(notification_type=Notification.TYPE_IMPORTANT_SENDER) |
            Q(importance_source=Notification.SOURCE_IMPORTANT_SENDER)
        ).count(),
        'ai_count': user_all_qs.filter(
            Q(notification_type=Notification.TYPE_AI_IMPORTANT) |
            Q(importance_source=Notification.SOURCE_AI)
        ).count(),
    }
    return render(request, 'notifications.html', context)


@login_required
def important_notifications_view(request):
    """
    Dedicated view for Important Notifications (/notifications/important/).
    """
    return redirect('/notifications/?tab=important')


@login_required
@require_http_methods(['GET', 'POST'])
def mark_notification_read_view(request, notification_id):
    """
    Marks a notification as read and records read_at timestamp.
    Accepts both JSON AJAX and standard HTTP POST/GET requests.
    """
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=['is_read', 'read_at'])

    unread_count = get_unread_count(request.user)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'id': notification.id,
            'unread_count': unread_count
        })

    messages.success(request, "Notification marked as read.")
    return redirect(request.META.get('HTTP_REFERER', 'notifications:index'))


@login_required
@require_http_methods(['GET', 'POST'])
def mark_all_notifications_read_view(request):
    """
    Marks all notifications for the authenticated user as read.
    """
    count = mark_all_read(request.user)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'marked_count': count,
            'unread_count': 0
        })

    messages.success(request, f"Marked {count} notifications as read.")
    return redirect(request.META.get('HTTP_REFERER', 'notifications:index'))


@login_required
@require_http_methods(['POST', 'DELETE'])
def delete_notification_view(request, notification_id):
    """
    Safely deletes a notification without affecting the underlying Email object.
    Enforces user ownership.
    """
    deleted = delete_notification(notification_id, request.user)
    if not deleted:
        return JsonResponse({'success': False, 'error': 'Notification not found or forbidden'}, status=404)

    unread_count = get_unread_count(request.user)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.method == 'DELETE':
        return JsonResponse({
            'success': True,
            'id': notification_id,
            'unread_count': unread_count
        })

    messages.success(request, "Notification deleted.")
    return redirect(request.META.get('HTTP_REFERER', 'notifications:index'))


@login_required
def unread_count_view(request):
    """
    Lightweight endpoint returning the total unread notifications count.
    Used for short-polling fallback when WebSockets are unavailable.
    """
    unread = get_unread_count(request.user)
    return JsonResponse({'unread_count': unread})


@login_required
@require_http_methods(['GET', 'POST'])
def notification_settings_view(request):
    """
    Updates user notification preferences.
    """
    pref = NotificationPreference.get_for_user(request.user)

    if request.method == 'POST':
        pref.browser_enabled = 'browser_enabled' in request.POST
        pref.push_enabled = 'push_enabled' in request.POST
        pref.important_email_enabled = 'important_email_enabled' in request.POST
        pref.important_sender_enabled = 'important_sender_enabled' in request.POST
        pref.ai_important_enabled = 'ai_important_enabled' in request.POST
        pref.sound_enabled = 'sound_enabled' in request.POST
        pref.gmail_important_enabled = 'gmail_important_enabled' in request.POST
        pref.notify_pinned_enabled = 'notify_pinned_enabled' in request.POST
        pref.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Notification preferences saved.'})

        messages.success(request, "Notification preferences updated successfully.")
        return redirect('/settings/#notificationsTabPane')

    return render(request, 'settings.html', {'active_tab': 'notifications'})


@login_required
@require_POST
def push_subscribe_view(request):
    """
    Registers or updates a Web Push subscription endpoint for the user.
    """
    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint', '').strip()
        p256dh = data.get('p256dh', '').strip()
        auth = data.get('auth', '').strip()
        user_agent = data.get('user_agent', '')[:255]

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'success': False, 'error': 'Invalid subscription payload'}, status=400)

        sub, created = PushSubscription.objects.update_or_create(
            user=request.user,
            endpoint=endpoint,
            defaults={
                'p256dh': p256dh,
                'auth': auth,
                'user_agent': user_agent
            }
        )
        return JsonResponse({'success': True, 'created': created, 'id': sub.id})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
@require_POST
def test_notification_view(request):
    """
    Triggers an explicit test notification for the authenticated user.
    """
    notif = create_test_notification(request.user)
    unread_count = get_unread_count(request.user)
    return JsonResponse({
        'success': True,
        'message': 'Test notification dispatched successfully.',
        'notification_id': notif.id,
        'unread_count': unread_count
    })

from django.contrib import admin
from .models import Notification, NotificationPreference, PushSubscription


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'notification_type', 'importance_source', 'priority', 'is_read', 'created_at')
    list_filter = ('notification_type', 'importance_source', 'priority', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'user__username', 'deduplication_key')
    readonly_fields = ('created_at', 'read_at')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'browser_enabled', 'push_enabled', 'important_sender_enabled', 'ai_important_enabled', 'sound_enabled')
    search_fields = ('user__username', 'user__email')


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'endpoint', 'created_at')
    search_fields = ('user__username', 'endpoint')
    readonly_fields = ('created_at', 'updated_at')

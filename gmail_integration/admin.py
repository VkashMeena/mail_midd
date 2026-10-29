from django.contrib import admin
from .models import GmailAccount, GmailSyncLog

@admin.register(GmailAccount)
class GmailAccountAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'email_address',
        'provider',
        'is_connected',
        'is_active',
        'last_connected_at',
        'last_synced_at'
    )
    list_filter = ('is_connected', 'is_active', 'provider', 'created_at')
    search_fields = ('email_address', 'user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'last_connected_at', 'last_synced_at')

    # Security: explicitly exclude raw and encrypted access and refresh tokens from admin
    exclude = ('encrypted_access_token', 'encrypted_refresh_token', 'scopes')


@admin.register(GmailSyncLog)
class GmailSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        'gmail_account',
        'status',
        'started_at',
        'completed_at',
        'fetched_count',
        'created_count',
        'updated_count',
        'failed_count'
    )
    list_filter = ('status', 'gmail_account', 'started_at')
    readonly_fields = ('started_at', 'completed_at')

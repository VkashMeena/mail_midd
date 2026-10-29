from django.contrib import admin
from .models import Email, EmailAttachment, PrioritySender, EmailSummary, EmailReply, ReplyTemplate, ReplyAuditLog


class EmailAttachmentInline(admin.TabularInline):
    model = EmailAttachment
    extra = 0
    readonly_fields = ('filename', 'mime_type', 'size', 'created_at')


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = (
        'subject',
        'effective_sender_name',
        'user',
        'ai_category',
        'ai_is_important',
        'ai_priority',
        'ai_status',
        'ai_processed_at',
        'received_at',
        'is_read',
        'has_attachments'
    )
    list_filter = (
        'ai_status',
        'ai_category',
        'ai_is_important',
        'ai_priority',
        'is_read',
        'is_starred',
        'is_pinned',
        'gmail_is_important',
        'has_attachments',
        'received_at'
    )
    search_fields = ('sender_name', 'sender_email', 'subject', 'body_text', 'ai_reason', 'gmail_message_id')
    readonly_fields = ('created_at', 'updated_at', 'ai_processed_at')
    inlines = [EmailAttachmentInline]
    date_hierarchy = 'received_at'


@admin.register(EmailAttachment)
class EmailAttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'email', 'mime_type', 'size', 'created_at')
    search_fields = ('filename', 'email__subject', 'email__sender_email')
    list_filter = ('mime_type', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(PrioritySender)
class PrioritySenderAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'email_address', 'user', 'is_important', 'priority', 'notification_enabled', 'is_active', 'is_demo')
    list_filter = ('is_important', 'priority', 'notification_enabled', 'is_active', 'is_demo')
    search_fields = ('display_name', 'email_address')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(EmailSummary)
class EmailSummaryAdmin(admin.ModelAdmin):
    list_display = ('summary_date', 'user', 'ai_status', 'total_emails', 'important_count', 'updated_at')
    list_filter = ('ai_status', 'summary_date')
    search_fields = ('user__username', 'overview')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(EmailReply)
class EmailReplyAdmin(admin.ModelAdmin):
    list_display = ('subject', 'recipient', 'user', 'reply_type', 'tone', 'status', 'sent_at', 'created_at')
    list_filter = ('reply_type', 'tone', 'status', 'created_at')
    search_fields = ('subject', 'recipient', 'generated_text', 'edited_text', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'sent_at')


@admin.register(ReplyTemplate)
class ReplyTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'is_default', 'created_at')
    list_filter = ('is_default', 'created_at')
    search_fields = ('name', 'content')


@admin.register(ReplyAuditLog)
class ReplyAuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'email', 'reply', 'timestamp')
    list_filter = ('action', 'timestamp')
    search_fields = ('user__username', 'details')
    readonly_fields = ('timestamp',)

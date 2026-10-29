from django.db import models
from django.conf import settings


class Notification(models.Model):
    # Notification Types
    TYPE_IMPORTANT_EMAIL = 'important_email'
    TYPE_IMPORTANT_SENDER = 'important_sender'
    TYPE_AI_IMPORTANT = 'ai_important'
    TYPE_USER_IMPORTANT = 'user_important'
    TYPE_AI_SUMMARY = 'ai_summary'
    TYPE_SECURITY = 'security'
    TYPE_SYSTEM = 'system'

    TYPE_CHOICES = [
        (TYPE_IMPORTANT_EMAIL, 'Important Email'),
        (TYPE_IMPORTANT_SENDER, 'Important Sender Alert'),
        (TYPE_AI_IMPORTANT, 'AI Important Email'),
        (TYPE_USER_IMPORTANT, 'User Flagged Important'),
        (TYPE_AI_SUMMARY, 'AI Summary Ready'),
        (TYPE_SECURITY, 'Security Alert'),
        (TYPE_SYSTEM, 'System Notification'),
    ]

    # Priority Levels
    PRIORITY_HIGH = 'High'
    PRIORITY_MEDIUM = 'Medium'
    PRIORITY_LOW = 'Low'

    PRIORITY_CHOICES = [
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_LOW, 'Low'),
    ]

    # Traceable Importance Sources
    SOURCE_IMPORTANT_SENDER = 'IMPORTANT_SENDER'
    SOURCE_USER_OVERRIDE = 'USER_OVERRIDE'
    SOURCE_AI = 'AI'
    SOURCE_GMAIL = 'GMAIL'
    SOURCE_PINNED = 'PINNED'
    SOURCE_SYSTEM = 'SYSTEM'

    SOURCE_CHOICES = [
        (SOURCE_IMPORTANT_SENDER, 'Important Sender Rule'),
        (SOURCE_USER_OVERRIDE, 'User Override'),
        (SOURCE_AI, 'AI Detection'),
        (SOURCE_GMAIL, 'Gmail Important Header'),
        (SOURCE_PINNED, 'Pinned Email'),
        (SOURCE_SYSTEM, 'System Event'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    email = models.ForeignKey('emails.Email', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES, default=TYPE_SYSTEM)
    importance_source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default=SOURCE_SYSTEM)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_HIGH)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    action_url = models.CharField(max_length=500, blank=True)
    delivered_browser = models.BooleanField(default=False)
    delivered_push = models.BooleanField(default=False)
    delivery_error = models.CharField(max_length=255, blank=True)
    deduplication_key = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    is_demo = models.BooleanField(default=False, help_text="Phase 1 demonstration record")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'notification_type']),
            models.Index(fields=['user', 'priority']),
            models.Index(fields=['deduplication_key']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.title} - {self.user.username}"

    @property
    def icon_class(self):
        if self.notification_type == self.TYPE_IMPORTANT_EMAIL:
            if self.importance_source == self.SOURCE_IMPORTANT_SENDER:
                return 'bi-person-star text-warning'
            elif self.importance_source == self.SOURCE_AI:
                return 'bi-robot text-primary'
            elif self.importance_source == self.SOURCE_USER_OVERRIDE:
                return 'bi-bookmark-star-fill text-danger'

        mapping = {
            self.TYPE_IMPORTANT_EMAIL: 'bi-exclamation-triangle-fill text-danger',
            self.TYPE_IMPORTANT_SENDER: 'bi-person-star text-warning',
            self.TYPE_AI_IMPORTANT: 'bi-robot text-primary',
            self.TYPE_USER_IMPORTANT: 'bi-bookmark-star-fill text-danger',
            self.TYPE_AI_SUMMARY: 'bi-stars text-primary',
            self.TYPE_SECURITY: 'bi-shield-lock-fill text-warning',
            self.TYPE_SYSTEM: 'bi-bell-fill text-secondary',
        }
        return mapping.get(self.notification_type, 'bi-bell text-info')

    @property
    def badge_class(self):
        mapping = {
            self.PRIORITY_HIGH: 'bg-danger text-white',
            self.PRIORITY_MEDIUM: 'bg-warning text-dark',
            self.PRIORITY_LOW: 'bg-secondary text-white',
        }
        return mapping.get(self.priority, 'bg-primary text-white')


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preference')
    browser_enabled = models.BooleanField(default=True, help_text="Enable HTML5 desktop browser notifications")
    push_enabled = models.BooleanField(default=False, help_text="Enable mobile/PWA web push notifications")
    important_email_enabled = models.BooleanField(default=True, help_text="Notify on important emails")
    important_sender_enabled = models.BooleanField(default=True, help_text="Notify when high-priority sender emails arrive")
    ai_important_enabled = models.BooleanField(default=True, help_text="Notify when AI classifies an email as important")
    sound_enabled = models.BooleanField(default=True, help_text="Play audible chime on notification arrival")
    email_notifications_enabled = models.BooleanField(default=False, help_text="Send email digests/alerts")
    gmail_important_enabled = models.BooleanField(default=False, help_text="Notify on Gmail IMPORTANT label")
    notify_pinned_enabled = models.BooleanField(default=False, help_text="Notify when emails are pinned")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'

    def __str__(self):
        return f"Notification Preferences for {self.user.username}"

    @classmethod
    def get_for_user(cls, user):
        preference, _ = cls.objects.get_or_create(user=user)
        return preference


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.URLField(max_length=1000)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Push Subscription'
        verbose_name_plural = 'Push Subscriptions'
        constraints = [
            models.UniqueConstraint(fields=['user', 'endpoint'], name='unique_user_push_endpoint')
        ]
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"PushSubscription for {self.user.username} ({self.endpoint[:30]}...)"

from django.db import models
from django.conf import settings
from django.utils import timezone
from ai_engine.constants import (
    EMAIL_CATEGORIES,
    CATEGORY_META,
    ALLOWED_PRIORITIES,
    PRIORITY_META,
    normalize_category
)


class EmailCategory:
    EDUCATION = 'Education'
    WORK = 'Work'
    FINANCE = 'Finance'
    PERSONAL = 'Personal'
    SHOPPING = 'Shopping'
    BILLS = 'Bills'
    TRAVEL = 'Travel'
    SOCIAL = 'Social'
    PROMOTIONS = 'Promotions'
    JOBS = 'Jobs'
    GOVERNMENT = 'Government'
    HEALTHCARE = 'Healthcare'
    TECHNOLOGY = 'Technology'
    OTHER = 'Other'

    # Canonical & expected categories
    JOB_INTERNSHIP = 'Job/Internship'
    PROMOTION = 'Promotion'
    NEWSLETTER = 'Newsletter'
    NOTIFICATION = 'Notification'

    # Aliases for backward compatibility
    JOB_INTERNSHIP_LEGACY = 'Job & Internship'
    BILLS_PAYMENTS = 'Bills & Payments'
    NOTIFICATIONS = 'Notifications'

    CHOICES = [
        (EDUCATION, 'Education'),
        (JOB_INTERNSHIP, 'Job/Internship'),
        (WORK, 'Work'),
        (FINANCE, 'Finance'),
        (PERSONAL, 'Personal'),
        (SHOPPING, 'Shopping'),
        (PROMOTION, 'Promotion'),
        (NEWSLETTER, 'Newsletter'),
        (NOTIFICATION, 'Notification'),
        (OTHER, 'Other'),
        # Extended & backward-compatibility choices
        (BILLS, 'Bills'),
        (TRAVEL, 'Travel'),
        (SOCIAL, 'Social'),
        (PROMOTIONS, 'Promotions'),
        (JOBS, 'Jobs'),
        (GOVERNMENT, 'Government'),
        (HEALTHCARE, 'Healthcare'),
        (TECHNOLOGY, 'Technology'),
        (JOB_INTERNSHIP_LEGACY, 'Job & Internship'),
        (BILLS_PAYMENTS, 'Bills & Payments'),
        (NOTIFICATIONS, 'Notifications'),
    ]

    META = CATEGORY_META


class EmailPriority:
    HIGH = 'High'
    MEDIUM = 'Medium'
    LOW = 'Low'

    CHOICES = [
        (HIGH, 'High'),
        (MEDIUM, 'Medium'),
        (LOW, 'Low'),
    ]

    META = PRIORITY_META


class EmailImportance:
    IMPORTANT = 'Important'
    NORMAL = 'Normal'

    CHOICES = [
        (IMPORTANT, 'Important'),
        (NORMAL, 'Normal'),
    ]


class AIStatus:
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'

    CHOICES = [
        (PENDING, 'Pending'),
        (PROCESSING, 'Processing'),
        (COMPLETED, 'Completed'),
        (FAILED, 'Failed'),
    ]


class Email(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='emails')
    gmail_account = models.ForeignKey(
        'gmail_integration.GmailAccount',
        on_delete=models.CASCADE,
        related_name='emails',
        null=True,
        blank=True,
        db_index=True
    )

    sender_name = models.CharField(max_length=255)
    sender_email = models.EmailField(db_index=True)
    recipient_email = models.EmailField()
    cc = models.TextField(blank=True, default='')
    bcc = models.TextField(blank=True, default='')
    subject = models.CharField(max_length=500)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    snippet = models.CharField(max_length=300, blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Core status flags
    is_read = models.BooleanField(default=False)
    is_starred = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    is_important = models.BooleanField(default=False)
    gmail_is_important = models.BooleanField(default=False, db_index=True)
    has_attachments = models.BooleanField(default=False)
    gmail_labels = models.CharField(max_length=500, blank=True, default='')

    # Legacy baseline fields (preserved)
    category = models.CharField(
        max_length=50,
        choices=EmailCategory.CHOICES,
        default=EmailCategory.OTHER
    )
    priority = models.CharField(
        max_length=20,
        choices=EmailPriority.CHOICES,
        default=EmailPriority.MEDIUM
    )
    importance = models.CharField(
        max_length=20,
        choices=EmailImportance.CHOICES,
        default=EmailImportance.NORMAL
    )

    # Phase 5: AI Engine Classification Fields
    ai_category = models.CharField(
        max_length=50,
        choices=EmailCategory.CHOICES,
        blank=True,
        null=True,
        db_index=True
    )
    ai_is_important = models.BooleanField(default=False, db_index=True)
    ai_priority = models.CharField(
        max_length=20,
        choices=EmailPriority.CHOICES,
        blank=True,
        null=True,
        db_index=True
    )
    ai_confidence = models.FloatField(blank=True, null=True)
    ai_objective = models.CharField(max_length=500, blank=True, default='')
    ai_reason = models.CharField(max_length=500, blank=True, default='')
    action_required = models.BooleanField(default=False)
    ai_status = models.CharField(
        max_length=20,
        choices=AIStatus.CHOICES,
        default=AIStatus.PENDING,
        db_index=True
    )
    ai_processed_at = models.DateTimeField(blank=True, null=True)
    ai_error = models.TextField(blank=True, default='')

    # Phase 5: User Overrides (Preserves AI data separately)
    user_category = models.CharField(
        max_length=50,
        choices=EmailCategory.CHOICES,
        blank=True,
        null=True
    )
    user_is_important = models.BooleanField(blank=True, null=True)
    user_priority = models.CharField(
        max_length=20,
        choices=EmailPriority.CHOICES,
        blank=True,
        null=True
    )

    # Identifies seed/mock records in Phase 1
    is_demo = models.BooleanField(default=False, help_text="Phase 1 demonstration record")

    # Real Gmail tracking fields
    gmail_message_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    gmail_thread_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    gmail_history_id = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['user', '-received_at']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'is_important']),
            models.Index(fields=['user', 'gmail_is_important']),
            models.Index(fields=['user', 'is_pinned']),
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'is_starred']),
            models.Index(fields=['gmail_account', 'gmail_message_id']),
            # Phase 5 indexes
            models.Index(fields=['user', 'ai_status']),
            models.Index(fields=['user', 'ai_category']),
            models.Index(fields=['user', 'ai_is_important']),
            models.Index(fields=['user', 'ai_priority']),
            models.Index(fields=['sender_email']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['gmail_account', 'gmail_message_id'],
                name='unique_gmail_message'
            )
        ]

    def __str__(self):
        return f"{self.effective_sender_name}: {self.subject}"

    def save(self, *args, **kwargs):
        if not self.snippet and self.body_text:
            self.snippet = (self.body_text[:200] + '...') if len(self.body_text) > 200 else self.body_text
        if self.is_important:
            self.importance = EmailImportance.IMPORTANT
        super().save(*args, **kwargs)

    # --- Classification Status & Metadata Accessors ---
    @property
    def classification_status(self) -> str:
        return (self.ai_status or AIStatus.PENDING).lower()

    @classification_status.setter
    def classification_status(self, val: str):
        if val:
            self.ai_status = val.upper()

    @property
    def classified_at(self):
        return self.ai_processed_at

    @classified_at.setter
    def classified_at(self, val):
        self.ai_processed_at = val

    @property
    def classification_error(self) -> str:
        return self.ai_error

    @classification_error.setter
    def classification_error(self, val: str):
        self.ai_error = val or ''

    # --- Phase 5 Effective Resolution Properties ---

    @property
    def effective_category(self) -> str:
        """
        User override takes precedence over AI classification.
        Fallback to legacy category or 'Uncategorized'.
        """
        if self.user_category:
            return self.user_category
        if self.ai_category:
            return self.ai_category
        if self.category and self.category != EmailCategory.OTHER:
            return normalize_category(self.category)
        if self.ai_status == AIStatus.COMPLETED:
            return EmailCategory.OTHER
        return 'Uncategorized'

    @property
    def effective_category_meta(self) -> dict:
        cat = self.effective_category
        if cat in CATEGORY_META:
            return CATEGORY_META[cat]
        return CATEGORY_META.get(EmailCategory.OTHER, {
            'icon': 'bi-folder', 'color': 'secondary', 'bg': 'bg-secondary-subtle', 'text': 'text-secondary'
        })

    @property
    def effective_priority(self) -> str:
        if self.user_priority:
            return self.user_priority
        if self.ai_priority:
            return self.ai_priority
        return self.priority or EmailPriority.MEDIUM

    @property
    def effective_priority_meta(self) -> dict:
        return PRIORITY_META.get(self.effective_priority, PRIORITY_META[EmailPriority.MEDIUM])

    @property
    def matched_priority_sender(self):
        """
        Returns cached or queried PrioritySender for this sender email.
        """
        if hasattr(self, '_matched_priority_sender'):
            return self._matched_priority_sender
        if not self.sender_email or not self.user_id:
            return None
        self._matched_priority_sender = PrioritySender.objects.filter(
            user_id=self.user_id,
            email_address=self.sender_email.strip().lower()
        ).first()
        return self._matched_priority_sender

    @property
    def effective_sender_name(self) -> str:
        """
        Custom sender display name > Gmail sender name > raw email address.
        """
        sender = self.matched_priority_sender
        if sender and sender.display_name:
            return sender.display_name
        if self.sender_name and self.sender_name.strip():
            return self.sender_name.strip()
        return self.sender_email

    @property
    def effective_importance(self) -> bool:
        """
        Synthesizes user override, priority sender rules, pinned state,
        AI intelligence, and Gmail flags.
        """
        if self.user_is_important is not None:
            return self.user_is_important
        if self.is_pinned:
            return True
        sender = self.matched_priority_sender
        if sender and sender.is_important:
            return True
        if self.ai_is_important:
            return True
        if self.gmail_is_important:
            return True
        return bool(self.is_important)

    @property
    def effective_is_important(self) -> bool:
        """Alias for effective_importance."""
        return self.effective_importance

    @property
    def effective_importance_reason(self) -> str:
        """
        Returns a concise, human-readable reason for effective importance.
        """
        if self.user_is_important is True:
            return "Marked Important by you"
        if self.user_is_important is False:
            return "Marked Not Important by you"
        if self.is_pinned:
            return "Pinned to top by you"
        sender = self.matched_priority_sender
        if sender and sender.is_important:
            return f"{sender.display_name} is marked as an Important Sender"
        if self.ai_is_important:
            return self.ai_reason or "AI identified this email as Important"
        if self.gmail_is_important:
            return "Flagged Important in Gmail"
        if self.is_important:
            return "Flagged Important"
        return ""

    @property
    def category_meta(self):
        # Backward compatibility for templates using email.category_meta
        return self.effective_category_meta

    @property
    def priority_meta(self):
        # Backward compatibility for templates using email.priority_meta
        return self.effective_priority_meta

    @property
    def label_list(self):
        """Returns Gmail labels as a list of strings."""
        if not self.gmail_labels:
            return []
        if isinstance(self.gmail_labels, list):
            return [str(l).strip() for l in self.gmail_labels if str(l).strip()]
        return [l.strip() for l in str(self.gmail_labels).split(',') if l.strip()]

    @property
    def formatted_labels(self):
        """Returns formatted label badges with clean human-readable names and icons."""
        from emails.utils import get_formatted_labels_list
        return get_formatted_labels_list(self.gmail_labels)

    @property
    def clean_body_html(self) -> str:
        """Returns sanitized HTML body with leaked raw CSS blocks removed."""
        from emails.utils import clean_leaked_css_from_html
        return clean_leaked_css_from_html(self.body_html or '')

    @property
    def clean_body_text(self) -> str:
        """Returns plain text body with leaked raw CSS blocks removed."""
        from emails.utils import clean_leaked_css_from_text
        return clean_leaked_css_from_text(self.body_text or '')

    @property
    def clean_body_html_document(self) -> str:
        """
        Returns full standalone HTML5 document for isolated rendering inside sandboxed <iframe>.
        """
        from emails.utils import build_email_iframe_document
        return build_email_iframe_document(self.clean_body_html, title=self.subject)


class EmailAttachment(models.Model):
    email = models.ForeignKey(Email, on_delete=models.CASCADE, related_name='attachments')
    gmail_attachment_id = models.CharField(max_length=255, blank=True, default='')
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True, default='')
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['filename']

    def __str__(self):
        return f"{self.filename} ({self.size_formatted})"

    @property
    def size_formatted(self):
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        return f"{self.size / (1024 * 1024):.1f} MB"


class PrioritySender(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='priority_senders')
    email_address = models.EmailField(db_index=True)
    display_name = models.CharField(max_length=255)
    priority = models.CharField(
        max_length=20,
        choices=EmailPriority.CHOICES,
        default=EmailPriority.HIGH
    )
    is_important = models.BooleanField(default=True, db_index=True)
    notification_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_name']
        unique_together = ('user', 'email_address')

    def __str__(self):
        return f"{self.display_name} <{self.email_address}> ({self.priority})"

    def save(self, *args, **kwargs):
        # Case normalization for reliable matching
        if self.email_address:
            self.email_address = self.email_address.strip().lower()
        super().save(*args, **kwargs)

    @property
    def priority_meta(self):
        return EmailPriority.META.get(self.priority, EmailPriority.META[EmailPriority.HIGH])


class EmailSummary(models.Model):
    """
    Persisted daily email intelligence briefing for Phase 7.
    Aggregates category counts, importance metrics, key highlights, and action items.
    """
    STATUS_PENDING = 'PENDING'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='email_summaries',
        db_index=True
    )
    summary_date = models.DateField(db_index=True)
    total_emails = models.PositiveIntegerField(default=0)
    important_count = models.PositiveIntegerField(default=0)
    high_priority_count = models.PositiveIntegerField(default=0)
    unread_count = models.PositiveIntegerField(default=0)

    # Structured AI Outputs
    overview = models.TextField(blank=True)
    important_points = models.JSONField(default=list, blank=True)
    action_items = models.JSONField(default=list, blank=True)
    category_summary = models.JSONField(default=list, blank=True)
    source_email_ids = models.JSONField(default=list, blank=True)

    ai_status = models.CharField(max_length=20, default=STATUS_PENDING, choices=STATUS_CHOICES, db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-summary_date']
        constraints = [
            models.UniqueConstraint(fields=['user', 'summary_date'], name='unique_user_daily_summary')
        ]
        indexes = [
            models.Index(fields=['user', '-summary_date']),
        ]

    def __str__(self):
        return f"Daily Summary ({self.summary_date}) - {self.user.username} [{self.ai_status}]"

    @property
    def total_emails_analyzed(self):
        return self.total_emails

    @total_emails_analyzed.setter
    def total_emails_analyzed(self, value):
        self.total_emails = value

    @property
    def important_emails_count(self):
        return self.important_count

    @important_emails_count.setter
    def important_emails_count(self, value):
        self.important_count = value

    @property
    def unread_emails_count(self):
        return self.unread_count

    @unread_emails_count.setter
    def unread_emails_count(self, value):
        self.unread_count = value



class EmailReply(models.Model):
    """
    Draft and sent email replies for Phase 7.
    Supports AI-generated drafts, static templates, manual edits, and audit status tracking.
    """
    TYPE_AI_GENERATED = 'AI_GENERATED'
    TYPE_STATIC_TEMPLATE = 'STATIC_TEMPLATE'
    TYPE_MANUAL = 'MANUAL'

    TYPE_CHOICES = [
        (TYPE_AI_GENERATED, 'AI Generated'),
        (TYPE_STATIC_TEMPLATE, 'Static Template'),
        (TYPE_MANUAL, 'Manual Draft'),
    ]

    TONE_PROFESSIONAL = 'Professional'
    TONE_POLITE = 'Polite'
    TONE_FRIENDLY = 'Friendly'
    TONE_FORMAL = 'Formal'
    TONE_CASUAL = 'Casual'
    TONE_SHORT = 'Short'

    TONE_CHOICES = [
        (TONE_PROFESSIONAL, 'Professional'),
        (TONE_POLITE, 'Polite'),
        (TONE_FRIENDLY, 'Friendly'),
        (TONE_FORMAL, 'Formal'),
        (TONE_CASUAL, 'Casual'),
        (TONE_SHORT, 'Short'),
    ]

    LENGTH_SHORT = 'Short'
    LENGTH_MEDIUM = 'Medium'
    LENGTH_LONG = 'Long'
    LENGTH_DETAILED = 'Detailed'

    LENGTH_CHOICES = [
        (LENGTH_SHORT, 'Short'),
        (LENGTH_MEDIUM, 'Medium'),
        (LENGTH_LONG, 'Long'),
        (LENGTH_DETAILED, 'Detailed'),
    ]

    STATUS_GENERATED = 'GENERATED'
    STATUS_EDITED = 'EDITED'
    STATUS_SAVED = 'SAVED'
    STATUS_SENDING = 'SENDING'
    STATUS_SENT = 'SENT'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_GENERATED, 'Generated Draft'),
        (STATUS_EDITED, 'Edited'),
        (STATUS_SAVED, 'Saved Draft'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='email_replies')
    email = models.ForeignKey(Email, on_delete=models.CASCADE, related_name='replies')
    reply_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_AI_GENERATED)
    tone = models.CharField(max_length=30, choices=TONE_CHOICES, default=TONE_PROFESSIONAL)
    length = models.CharField(max_length=20, choices=LENGTH_CHOICES, default=LENGTH_MEDIUM)
    instruction = models.TextField(blank=True)

    recipient = models.EmailField(max_length=254)
    subject = models.CharField(max_length=500)
    generated_text = models.TextField(blank=True)
    edited_text = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_GENERATED, db_index=True)
    gmail_message_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', '-created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Reply to {self.recipient} ({self.status}) - {self.user.username}"

    @property
    def final_text(self):
        """Returns edited text if modified, else original generated text."""
        return self.edited_text if self.edited_text else self.generated_text

    @property
    def reply_length(self) -> str:
        return self.length

    @reply_length.setter
    def reply_length(self, value: str):
        self.length = value

    @property
    def reply_tone(self) -> str:
        return self.tone

    @reply_tone.setter
    def reply_tone(self, value: str):
        self.tone = value

    @property
    def custom_instruction(self) -> str:
        return self.instruction

    @custom_instruction.setter
    def custom_instruction(self, value: str):
        self.instruction = value

    @property
    def format_label(self) -> str:
        return f"{self.length} + {self.tone}"


class ReplyTemplate(models.Model):
    """
    Reusable static reply templates for Phase 7.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='reply_templates')
    name = models.CharField(max_length=100)
    content = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        owner = self.user.username if self.user else "System"
        return f"{self.name} ({owner})"

    @classmethod
    def get_templates_for_user(cls, user):
        """Returns system default templates plus the user's custom templates."""
        return cls.objects.filter(models.Q(user=user) | models.Q(user__isnull=True, is_default=True)).order_by('name')


class ReplyAuditLog(models.Model):
    """
    Audit trail tracking reply generation, edits, drafts, and dispatch events.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reply_audit_logs')
    email = models.ForeignKey(Email, on_delete=models.SET_NULL, null=True, blank=True, related_name='reply_audit_logs')
    reply = models.ForeignKey(EmailReply, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=30, choices=EmailReply.STATUS_CHOICES)
    details = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
        ]

    def __str__(self):
        return f"[{self.action}] by {self.user.username} at {self.timestamp}"


class EmailAnalysis(models.Model):
    """
    Detailed intelligence analysis produced by the AI Engine / Groq Analyzer.
    Stores extracted objective, category, sentiment, urgency, key points, action items,
    deadlines, and suggested reply hooks.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='email_analyses')
    email = models.OneToOneField(Email, on_delete=models.CASCADE, related_name='analysis')
    provider = models.CharField(max_length=50, default='groq')
    model_name = models.CharField(max_length=100, default='llama-3.3-70b-versatile')
    objective = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, blank=True, default='')
    priority = models.CharField(max_length=20, blank=True, default='Medium')
    is_important = models.BooleanField(default=False)
    urgency = models.CharField(max_length=50, blank=True, default='Normal')
    sentiment = models.CharField(max_length=50, blank=True, default='Professional')
    confidence = models.FloatField(default=0.9)
    reason = models.TextField(blank=True, default='')
    action_required = models.BooleanField(default=False)
    key_points = models.JSONField(default=list, blank=True)
    action_items = models.JSONField(default=list, blank=True)
    extracted_deadlines = models.JSONField(default=list, blank=True)
    suggested_reply_hooks = models.JSONField(default=list, blank=True)
    raw_response = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Email Analyses'
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Analysis for: {self.email.subject} ({self.category})"



from django.db import models
from django.conf import settings
from django.utils import timezone
from .crypto import encrypt_token, decrypt_token

class GmailAccount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gmail_accounts',
        db_index=True
    )
    email_address = models.EmailField(max_length=255, db_index=True)
    provider = models.CharField(max_length=50, default='google')

    is_connected = models.BooleanField(default=True, db_index=True)
    is_active = models.BooleanField(default=True)

    # Secure credentials stored encrypted at rest
    encrypted_access_token = models.TextField(blank=True, default='')
    encrypted_refresh_token = models.TextField(blank=True, default='')
    token_expiry = models.DateTimeField(null=True, blank=True)
    scopes = models.TextField(blank=True, default='')

    last_connected_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_connected'], name='idx_gmail_user_connected'),
            models.Index(fields=['email_address'], name='idx_gmail_email_address'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'email_address'],
                name='unique_user_gmail_account'
            )
        ]

    def save(self, *args, **kwargs):
        if self.email_address:
            self.email_address = self.email_address.strip().lower()
        super().save(*args, **kwargs)

    def set_access_token(self, token: str):
        """Encrypts and sets the access token."""
        self.encrypted_access_token = encrypt_token(token) if token else ''

    def get_access_token(self) -> str:
        """Decrypts and returns the access token."""
        return decrypt_token(self.encrypted_access_token) if self.encrypted_access_token else ''

    def set_refresh_token(self, token: str):
        """Encrypts and sets the refresh token."""
        self.encrypted_refresh_token = encrypt_token(token) if token else ''

    def get_refresh_token(self) -> str:
        """Decrypts and returns the refresh token."""
        return decrypt_token(self.encrypted_refresh_token) if self.encrypted_refresh_token else ''

    # Property transparent access for convenience & backwards compatibility
    @property
    def access_token(self) -> str:
        return self.get_access_token()

    @access_token.setter
    def access_token(self, value: str):
        self.set_access_token(value)

    @property
    def refresh_token(self) -> str:
        return self.get_refresh_token()

    @refresh_token.setter
    def refresh_token(self, value: str):
        self.set_refresh_token(value)

    def __str__(self):
        status = "Connected" if self.is_connected else "Disconnected"
        return f"{self.email_address} ({status}) - {self.user}"

    @property
    def masked_email(self):
        """Safe representation for UI"""
        parts = self.email_address.split('@')
        if len(parts) == 2 and len(parts[0]) > 2:
            return f"{parts[0][:2]}***@{parts[1]}"
        return self.email_address

    @property
    def has_read_permission(self) -> bool:
        """Checks if the account has been granted Gmail read permissions."""
        if not self.scopes:
            return False
        return 'gmail.readonly' in self.scopes or 'https://www.googleapis.com/auth/gmail.readonly' in self.scopes

    @property
    def has_send_permission(self) -> bool:
        """Checks if the account has been explicitly granted Gmail send permissions."""
        if not self.scopes:
            return False
        return 'gmail.send' in self.scopes or 'https://www.googleapis.com/auth/gmail.send' in self.scopes




class GmailSyncLog(models.Model):
    STATUS_CHOICES = [
        ('RUNNING', 'Running'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    gmail_account = models.ForeignKey(
        GmailAccount,
        on_delete=models.CASCADE,
        related_name='sync_logs',
        db_index=True
    )
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RUNNING', db_index=True)
    fetched_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['gmail_account', '-started_at'], name='idx_synclog_acc_started'),
        ]

    def __str__(self):
        return f"Sync ({self.status}) for {self.gmail_account.email_address} at {self.started_at}"

    @property
    def duration_seconds(self):
        if self.completed_at and self.started_at:
            return round((self.completed_at - self.started_at).total_seconds(), 1)
        return None

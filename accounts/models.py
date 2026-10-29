from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.exceptions import ValidationError
import os

class User(AbstractUser):
    """
    Custom user model where email is the primary login identifier.
    Preserves username for backward compatibility and display.
    """
    email = models.EmailField('email address', unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email or self.username


def validate_avatar_file(file):
    """
    Validates uploaded avatar file type and size.
    Prohibits executable or malicious files.
    """
    max_size_mb = 2
    if file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f"Avatar file size cannot exceed {max_size_mb} MB.")

    valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in valid_extensions:
        raise ValidationError(
            f"Unsupported file extension '{ext}'. Allowed formats: JPG, JPEG, PNG, WEBP."
        )

    # Basic content type check if available
    content_type = getattr(file, 'content_type', '')
    if content_type and not content_type.startswith('image/'):
        raise ValidationError("Uploaded file must be a valid image.")


class UserProfile(models.Model):
    THEME_CHOICES = [
        ('light', 'Light Mode'),
        ('dark', 'Dark Mode'),
        ('system', 'System Default'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    display_name = models.CharField(max_length=150, blank=True)
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        validators=[validate_avatar_file]
    )
    timezone = models.CharField(max_length=64, default='UTC')
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='light')
    is_google_connected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.display_name or self.user.email}'s Profile"

    def get_display_name(self):
        if self.display_name:
            return self.display_name
        full = self.user.get_full_name()
        return full if full else (self.user.username or self.user.email)

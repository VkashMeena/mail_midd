"""
Phase 8: Final Integration, Multi-Tenant Security, Logging & Production Readiness Tests.
"""
import json
import logging
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from datetime import date

from config.logging_filters import SensitiveDataFilter
from config.views import health_check_view, error_400_view, error_403_view, error_404_view, error_429_view, error_500_view
from emails.models import (
    Email,
    EmailSummary,
    EmailReply,
    EmailCategory,
    EmailPriority,
    EmailImportance,
    AIStatus,
)
from gmail_integration.models import GmailAccount
from notifications.models import Notification
from emails.tasks import sync_gmail_account_task
from ai_engine.tasks import classify_unprocessed_emails_task, generate_daily_summary_task

User = get_user_model()


class ProductionSettingsHardeningTests(TestCase):
    """Verifies security headers, static asset configuration, and session protection."""

    def test_whitenoise_middleware_configured(self):
        self.assertIn(
            'whitenoise.middleware.WhiteNoiseMiddleware',
            settings.MIDDLEWARE,
            "WhiteNoiseMiddleware must be present in MIDDLEWARE for production static asset delivery."
        )

    def test_cookie_and_security_headers_configured(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.SECURE_REFERRER_POLICY, 'same-origin')

    def test_celery_configuration_configured(self):
        self.assertTrue(hasattr(settings, 'CELERY_BROKER_URL'))
        self.assertEqual(settings.CELERY_TASK_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_RESULT_SERIALIZER, 'json')


class HealthCheckEndpointTests(TestCase):
    """Verifies /health/ endpoint for uptime monitoring and container probes."""

    def setUp(self):
        self.client = Client()

    def test_health_check_endpoint_returns_200_when_healthy(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'healthy')
        self.assertEqual(data.get('service'), 'AI Smart Mail Manager')
        self.assertEqual(data.get('version'), '1.0.0')

    @patch('django.db.connection.cursor')
    def test_health_check_endpoint_returns_503_when_database_down(self, mock_cursor):
        mock_cursor.side_effect = Exception("Database connection refused")
        request = RequestFactory().get('/health/')
        response = health_check_view(request)
        self.assertEqual(response.status_code, 503)
        data = json.loads(response.content.decode('utf-8'))
        self.assertEqual(data.get('status'), 'unhealthy')
        self.assertIn('Database connection refused', data.get('database'))


class MultiTenantIsolationSecurityTests(TestCase):
    """
    Enforces strict zero-leakage isolation between user accounts.
    User A must NEVER be able to view, query, or mutate User B's emails, notifications, or replies.
    """

    def setUp(self):
        self.user_a = User.objects.create_user(
            username='user_alice',
            email='alice@example.com',
            password='Password123!'
        )
        self.user_b = User.objects.create_user(
            username='user_bob',
            email='bob@example.com',
            password='Password123!'
        )

        self.account_b = GmailAccount.objects.create(
            user=self.user_b,
            email_address='bob.gmail@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
            is_active=True
        )

        self.email_b = Email.objects.create(
            user=self.user_b,
            gmail_account=self.account_b,
            gmail_message_id='bob_mail_001',
            gmail_thread_id='bob_thread_001',
            sender_email='confidential@bank.com',
            sender_name='Bank Alerts',
            recipient_email='bob.gmail@example.com',
            subject='Confidential Statement for Bob',
            body_text='Your balance is $50,000.',
            received_at=timezone.now(),
            ai_category=EmailCategory.FINANCE,
            ai_priority=EmailPriority.HIGH,
            ai_status=AIStatus.COMPLETED
        )

        self.notification_b = Notification.objects.create(
            user=self.user_b,
            email=self.email_b,
            title='Urgent Bank Notice',
            message='Your bank statement is available.',
            notification_type='high_priority'
        )

        self.client_a = Client()
        self.client_a.login(username='alice@example.com', password='Password123!')

    def test_user_a_cannot_view_user_b_email_detail(self):
        url = reverse('emails:detail', kwargs={'email_id': self.email_b.pk})
        response = self.client_a.get(url)
        # Should return 404 Not Found (or 403 Forbidden) to prevent resource enumeration
        self.assertIn(response.status_code, [403, 404])

    def test_user_a_cannot_mark_user_b_notification_read(self):
        url = reverse('notifications:mark_read', kwargs={'notification_id': self.notification_b.pk})
        response = self.client_a.post(url)
        self.assertIn(response.status_code, [403, 404])
        self.notification_b.refresh_from_db()
        self.assertFalse(self.notification_b.is_read)

    def test_user_a_cannot_access_user_b_email_reply_interface(self):
        url = reverse('email_reply', kwargs={'email_id': self.email_b.pk})
        response = self.client_a.get(url)
        self.assertIn(response.status_code, [403, 404])

    def test_user_a_cannot_send_reply_for_user_b_email(self):
        url = reverse('email_reply_send', kwargs={'email_id': self.email_b.pk})
        response = self.client_a.post(url, {
            'reply_body': 'Unauthorized reply attempt',
            'action_type': 'send_now'
        })
        self.assertIn(response.status_code, [403, 404])


class CustomErrorViewsTests(TestCase):
    """Verifies that all custom error views (400, 403, 404, 429, 500) render valid HTML templates."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_error_400_renders_correctly(self):
        request = self.factory.get('/bad-request/')
        response = error_400_view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'400', response.content)
        self.assertIn(b'Bad Request', response.content)

    def test_error_403_renders_correctly(self):
        request = self.factory.get('/forbidden/')
        response = error_403_view(request)
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'403', response.content)
        self.assertIn(b'Access Denied', response.content)

    def test_error_404_renders_correctly(self):
        request = self.factory.get('/not-found/')
        response = error_404_view(request)
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'404', response.content)
        self.assertIn(b'Page Not Found', response.content)

    def test_error_429_renders_correctly(self):
        request = self.factory.get('/rate-limited/')
        response = error_429_view(request)
        self.assertEqual(response.status_code, 429)
        self.assertIn(b'429', response.content)
        self.assertIn(b'Too Many Requests', response.content)

    def test_error_500_renders_correctly(self):
        request = self.factory.get('/server-error/')
        response = error_500_view(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn(b'500', response.content)
        self.assertIn(b'Internal System Error', response.content)


class SensitiveDataFilterLoggingTests(TestCase):
    """Verifies that sensitive credentials, tokens, and keys are scrubbed before logging."""

    def setUp(self):
        self.filter = SensitiveDataFilter()

    def test_scrubs_google_oauth_tokens(self):
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg='Fetched token ya29.a0AfH6SMBxyz1234567890abcdef for user',
            args=(),
            exc_info=None
        )
        self.filter.filter(record)
        self.assertNotIn('ya29.a0AfH6SMBxyz1234567890abcdef', record.msg)
        self.assertIn('ya29.[REDACTED]', record.msg)

    def test_scrubs_bearer_authorization_headers(self):
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=20,
            msg='HTTP Header Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz',
            args=(),
            exc_info=None
        )
        self.filter.filter(record)
        self.assertNotIn('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz', record.msg)
        self.assertIn('Bearer [REDACTED]', record.msg)

    def test_scrubs_openai_api_keys(self):
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=30,
            msg='Configuring client with key sk-abcdef1234567890abcdef1234567890',
            args=(),
            exc_info=None
        )
        self.filter.filter(record)
        self.assertNotIn('sk-abcdef1234567890abcdef1234567890', record.msg)
        self.assertIn('sk-[REDACTED]', record.msg)

    def test_scrubs_passwords_and_secrets(self):
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=40,
            msg='Failed payload: {"password": "SuperSecretPassword123!", "status": "failed"}',
            args=(),
            exc_info=None
        )
        self.filter.filter(record)
        self.assertNotIn('SuperSecretPassword123!', record.msg)
        self.assertIn('[REDACTED]', record.msg)


class CeleryTaskUnitTests(TestCase):
    """Verifies that background Celery tasks execute without syntax or import errors."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='celery_test_user',
            email='celery_test@example.com',
            password='Password123!'
        )

    def test_sync_gmail_account_task_no_accounts(self):
        result = sync_gmail_account_task(user_id=self.user.id)
        self.assertEqual(result.get('status'), 'skipped')
        self.assertEqual(result.get('synced'), 0)

    def test_classify_unprocessed_emails_task_empty_queue(self):
        result = classify_unprocessed_emails_task(user_id=self.user.id)
        self.assertEqual(result.get('status'), 'skipped')
        self.assertEqual(result.get('processed'), 0)

    @patch('ai_engine.summarizer.EmailSummarizer.summarize_for_user')
    def test_generate_daily_summary_task(self, mock_summarize):
        mock_summarize.return_value = None
        result = generate_daily_summary_task(user_id=self.user.id)
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('summaries_generated'), 1)

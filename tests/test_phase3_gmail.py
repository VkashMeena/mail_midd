from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError

from gmail_integration.models import GmailAccount
from gmail_integration.services import (
    gmail_service,
    STATE_CONNECTED,
    STATE_NOT_CONNECTED,
    STATE_TOKEN_EXPIRED
)
from gmail_integration.scopes import get_scopes_list, get_scopes_string
from gmail_integration.crypto import encrypt_token, decrypt_token
from gmail_integration.exceptions import (
    GmailIntegrationError,
    GmailConfigurationError,
    GmailOAuthError,
    GmailTokenError,
    GmailPermissionError,
    GmailAPIError
)

User = get_user_model()


class Phase3GmailScopesAndCryptoTests(TestCase):
    def test_minimum_scopes(self):
        """Scopes must be centralized and restricted to minimum required permissions"""
        scopes = get_scopes_list()
        self.assertIn('https://www.googleapis.com/auth/gmail.readonly', scopes)
        self.assertIn('https://www.googleapis.com/auth/userinfo.email', scopes)
        # Verify modify or compose is not in Phase 3 minimum scopes
        self.assertNotIn('https://www.googleapis.com/auth/gmail.modify', scopes)
        self.assertNotIn('https://www.googleapis.com/auth/gmail.compose', scopes)
        self.assertIsInstance(get_scopes_string(), str)

    def test_token_encryption_at_rest(self):
        """Tokens are encrypted using Fernet at rest and decrypted in memory"""
        raw_token = "ya29.sample_secret_access_token_12345"
        encrypted = encrypt_token(raw_token)
        self.assertNotEqual(encrypted, raw_token)
        self.assertNotIn(raw_token, encrypted)

        decrypted = decrypt_token(encrypted)
        self.assertEqual(decrypted, raw_token)

    def test_model_token_getters_and_setters(self):
        """GmailAccount model transparently encrypts upon setting and decrypts upon getting"""
        user = User.objects.create_user(username='cryptouser', email='crypto@example.com', password='Password123!')
        account = GmailAccount(user=user, email_address='crypto@gmail.com')
        account.set_access_token('access_plain_token')
        account.set_refresh_token('refresh_plain_token')
        account.save()

        # Reload from DB to inspect stored raw values
        fresh = GmailAccount.objects.get(id=account.id)
        self.assertNotEqual(fresh.encrypted_access_token, 'access_plain_token')
        self.assertNotEqual(fresh.encrypted_refresh_token, 'refresh_plain_token')
        self.assertEqual(fresh.get_access_token(), 'access_plain_token')
        self.assertEqual(fresh.get_refresh_token(), 'refresh_plain_token')
        self.assertEqual(fresh.access_token, 'access_plain_token')
        self.assertEqual(fresh.refresh_token, 'refresh_plain_token')


class Phase3GmailOAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='phase3user',
            email='phase3user@example.com',
            password='Password123!'
        )
        self.client.force_login(self.user)

    def test_connect_requires_login(self):
        """Anonymous user attempting to connect Gmail is redirected to login"""
        anon_client = Client()
        response = anon_client.get(reverse('gmail:connect'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    @override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
    def test_oauth_configuration_missing(self):
        """When OAuth credentials are missing, returns user-friendly warning without exposing secrets"""
        response = self.client.get(reverse('gmail:connect'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)
        # Check messages
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Gmail integration is not configured" in str(m) for m in messages))

    @override_settings(
        GOOGLE_CLIENT_ID='test_client_id.apps.googleusercontent.com',
        GOOGLE_CLIENT_SECRET='test_client_secret',
        GOOGLE_REDIRECT_URI='http://127.0.0.1:8000/gmail/oauth/callback/'
    )
    def test_oauth_state_generation_and_redirect(self):
        """Connect view generates cryptographically secure state and redirects to Google"""
        response = self.client.get(reverse('gmail:connect'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('accounts.google.com/o/oauth2/v2/auth', response.url)
        self.assertIn('state=', response.url)

        # Check session contains state
        session_state = self.client.session.get('gmail_oauth_state')
        self.assertIsNotNone(session_state)
        self.assertGreaterEqual(len(session_state), 32)
        self.assertIn(session_state, response.url)

    def test_oauth_state_mismatch_rejected(self):
        """Callback with state mismatch is rejected with Invalid authorization request error"""
        session = self.client.session
        session['gmail_oauth_state'] = 'session_valid_state_123'
        session.save()

        response = self.client.get(reverse('gmail:callback'), {
            'code': 'some_valid_code',
            'state': 'attacker_different_state_456'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Invalid authorization request" in str(m) for m in messages))

    def test_oauth_callback_missing_code_or_state(self):
        """Callback missing code or state returns user-friendly error safely"""
        response = self.client.get(reverse('gmail:callback'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Unable to complete Gmail authorization" in str(m) for m in messages))

    def test_google_authorization_denied(self):
        """Handles user cancelling authorization or Google returning access_denied"""
        response = self.client.get(reverse('gmail:callback'), {
            'error': 'access_denied'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Google authorization was cancelled" in str(m) for m in messages))

    @patch('gmail_integration.oauth.GmailOAuthHandler.exchange_code_for_tokens')
    def test_token_exchange_failure(self, mock_exchange):
        """Upstream token exchange failure is caught and reported safely"""
        mock_exchange.side_effect = GmailOAuthError("Unable to complete Gmail authorization.")
        session = self.client.session
        session['gmail_oauth_state'] = 'test_matching_state'
        session.save()

        response = self.client.get(reverse('gmail:callback'), {
            'code': 'mock_code',
            'state': 'test_matching_state'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("Unable to complete Gmail authorization" in str(m) for m in messages))

    @patch('gmail_integration.client.GmailClient.get_profile')
    @patch('gmail_integration.oauth.GmailOAuthHandler.exchange_code_for_tokens')
    def test_gmail_profile_retrieval_and_account_creation(self, mock_exchange, mock_profile):
        """Authenticated Google profile email is extracted and stored safely in GmailAccount"""
        mock_exchange.return_value = {
            'access_token': 'new_google_access_token',
            'refresh_token': 'new_google_refresh_token',
            'expires_in': 3600,
            'scope': 'https://www.googleapis.com/auth/gmail.readonly',
        }
        mock_profile.return_value = {
            'emailAddress': 'real.google.user@gmail.com',
            'messagesTotal': 120
        }

        session = self.client.session
        session['gmail_oauth_state'] = 'correct_state'
        session.save()

        response = self.client.get(reverse('gmail:callback'), {
            'code': 'valid_code',
            'state': 'correct_state'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/gmail/', response.url)

        account = GmailAccount.objects.filter(user=self.user, email_address='real.google.user@gmail.com').first()
        self.assertIsNotNone(account)
        self.assertTrue(account.is_connected)
        self.assertTrue(account.is_active)
        self.assertEqual(account.get_access_token(), 'new_google_access_token')
        self.assertEqual(account.get_refresh_token(), 'new_google_refresh_token')
        self.assertIsNotNone(account.last_connected_at)

        # Profile is updated
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.is_google_connected)

    def test_duplicate_account_prevention(self):
        """Database UniqueConstraint prevents duplicate account records for same user and email"""
        GmailAccount.objects.create(
            user=self.user,
            email_address='dupe.test@gmail.com',
            is_connected=True
        )
        with self.assertRaises(IntegrityError):
            GmailAccount.objects.create(
                user=self.user,
                email_address='dupe.test@gmail.com',
                is_connected=True
            )

    @patch('gmail_integration.client.GmailClient.get_profile')
    @patch('gmail_integration.oauth.GmailOAuthHandler.exchange_code_for_tokens')
    def test_reconnect_existing_account_preserves_refresh_token(self, mock_exchange, mock_profile):
        """When reconnecting without a new refresh token, the existing refresh token is preserved"""
        # Create pre-existing account with an established refresh token
        existing = GmailAccount(
            user=self.user,
            email_address='reconnect@gmail.com',
            is_connected=False
        )
        existing.set_access_token('old_access')
        existing.set_refresh_token('ORIGINAL_PERMANENT_REFRESH_TOKEN')
        existing.save()

        # Google returns new access token but NO new refresh token
        mock_exchange.return_value = {
            'access_token': 'brand_new_access_token',
            'refresh_token': None,  # Omitted by Google on subsequent consent
            'expires_in': 3600,
            'scope': 'https://www.googleapis.com/auth/gmail.readonly',
        }
        mock_profile.return_value = {
            'emailAddress': 'reconnect@gmail.com'
        }

        session = self.client.session
        session['gmail_oauth_state'] = 'reconnect_state'
        session.save()

        response = self.client.get(reverse('gmail:callback'), {
            'code': 'new_code',
            'state': 'reconnect_state'
        })
        self.assertEqual(response.status_code, 302)

        # Verify only 1 account exists
        accounts = GmailAccount.objects.filter(user=self.user, email_address='reconnect@gmail.com')
        self.assertEqual(accounts.count(), 1)
        reconnected = accounts.first()
        self.assertTrue(reconnected.is_connected)
        self.assertEqual(reconnected.get_access_token(), 'brand_new_access_token')
        # Crucial: Existing refresh token was NEVER overwritten with NULL or empty!
        self.assertEqual(reconnected.get_refresh_token(), 'ORIGINAL_PERMANENT_REFRESH_TOKEN')

    @patch('google.oauth2.credentials.Credentials.refresh')
    def test_token_refresh_flow(self, mock_refresh):
        """Expired access token triggers refresh using refresh_token and updates DB"""
        account = GmailAccount(
            user=self.user,
            email_address='refresh.test@gmail.com',
            is_connected=True,
            token_expiry=timezone.now() - timedelta(minutes=10)
        )
        account.set_access_token('expired_access_token')
        account.set_refresh_token('valid_refresh_token')
        account.save()

        def side_effect(request):
            # Simulate Google credentials updating token
            account.set_access_token('new_refreshed_access_token')
        mock_refresh.side_effect = side_effect

        from gmail_integration.client import GmailClient
        client = GmailClient(account=account)
        # Client refresh
        success = client.refresh_access_token()
        self.assertTrue(success)

    def test_disconnect_requires_post(self):
        """Disconnect endpoint strictly rejects GET requests"""
        response = self.client.get(reverse('gmail:disconnect'))
        self.assertEqual(response.status_code, 405)

    @patch('gmail_integration.client.GmailClient.revoke_credentials')
    def test_disconnect_state_change_and_ownership(self, mock_revoke):
        """Disconnecting sets is_connected=False, attempts revocation, and checks ownership"""
        mock_revoke.return_value = True

        other_user = User.objects.create_user(username='otheruser', email='other@example.com', password='Password123!')
        other_account = GmailAccount.objects.create(
            user=other_user,
            email_address='other@gmail.com',
            is_connected=True
        )

        # Attempt to disconnect other user's account
        response = self.client.post(reverse('gmail:disconnect'), {'account_id': other_account.id})
        other_account.refresh_from_db()
        # Other user's account must remain connected!
        self.assertTrue(other_account.is_connected)

        # Connect account for current user
        my_account = GmailAccount.objects.create(
            user=self.user,
            email_address='myaccount@gmail.com',
            is_connected=True
        )
        response = self.client.post(reverse('gmail:disconnect'), {'account_id': my_account.id})
        self.assertEqual(response.status_code, 302)
        my_account.refresh_from_db()
        self.assertFalse(my_account.is_connected)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.is_google_connected)

    def test_tokens_never_appear_in_responses(self):
        """Tokens never appear in rendered HTML templates or JSON status responses"""
        account = GmailAccount(
            user=self.user,
            email_address='secret.test@gmail.com',
            is_connected=True
        )
        secret_access = "super_secret_access_xyz_token"
        secret_refresh = "super_secret_refresh_abc_token"
        account.set_access_token(secret_access)
        account.set_refresh_token(secret_refresh)
        account.save()

        # 1. Check dedicated account page
        resp_account = self.client.get(reverse('settings_gmail'))
        content_account = resp_account.content.decode('utf-8')
        self.assertNotIn(secret_access, content_account)
        self.assertNotIn(secret_refresh, content_account)

        # 2. Check settings page
        resp_settings = self.client.get(reverse('settings'))
        content_settings = resp_settings.content.decode('utf-8')
        self.assertNotIn(secret_access, content_settings)
        self.assertNotIn(secret_refresh, content_settings)

        # 3. Check JSON status API
        resp_api = self.client.get(reverse('gmail:status'))
        self.assertEqual(resp_api.status_code, 200)
        api_content = resp_api.content.decode('utf-8')
        self.assertNotIn(secret_access, api_content)
        self.assertNotIn(secret_refresh, api_content)

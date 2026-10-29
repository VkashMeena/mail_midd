from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from gmail_integration.models import GmailAccount
from gmail_integration.services import gmail_service
from gmail_integration.exceptions import GmailAuthenticationError

User = get_user_model()

class GmailAccountModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='gmailuser',
            email='gmailuser@example.com',
            password='Password123!'
        )

    def test_gmail_account_creation_and_normalization(self):
        """Gmail account normalizes email to lowercase and initializes status"""
        account = GmailAccount.objects.create(
            user=self.user,
            email_address='User.Work@Gmail.COM  ',
            provider='google',
            is_connected=True,
            access_token='test_token',
            refresh_token='test_refresh'
        )
        self.assertEqual(account.email_address, 'user.work@gmail.com')
        self.assertTrue(account.is_connected)
        self.assertIn('Connected', str(account))
        self.assertEqual(account.masked_email, 'us***@gmail.com')

    def test_gmail_account_unique_constraint_per_user(self):
        """Duplicate Gmail account for the same user is prevented by database constraint"""
        GmailAccount.objects.create(
            user=self.user,
            email_address='primary@gmail.com',
            is_connected=True
        )
        with self.assertRaises(IntegrityError):
            GmailAccount.objects.create(
                user=self.user,
                email_address='primary@gmail.com',
                is_connected=True
            )


class GmailServiceAndOAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='oauthuser',
            email='oauthuser@example.com',
            password='Password123!'
        )
        self.client.force_login(self.user)

    def test_get_account_status_unconnected(self):
        """Status returns not_connected when user has no linked GmailAccount"""
        status = gmail_service.get_account_status(self.user)
        self.assertEqual(status['status'], 'not_connected')
        self.assertIsNone(status['email'])

    def test_get_account_status_connected(self):
        """Status returns connected and account email when active"""
        GmailAccount.objects.create(
            user=self.user,
            email_address='connected@gmail.com',
            is_connected=True,
            is_active=True
        )
        status = gmail_service.get_account_status(self.user)
        self.assertEqual(status['status'], 'connected')
        self.assertEqual(status['email'], 'connected@gmail.com')

    def test_oauth_connect_missing_credentials_shows_warning(self):
        """When GOOGLE_CLIENT_ID is unconfigured, connect view warns user and redirects safely without crashing"""
        with patch.object(gmail_service.oauth_handler, 'is_configured', return_value=False):
            response = self.client.get(reverse('gmail:connect'))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/settings/', response.url)

    def test_oauth_callback_state_mismatch_rejected(self):
        """Callback with invalid or tampered state must be rejected"""
        # Set session state
        session = self.client.session
        session['gmail_oauth_state'] = 'valid_session_state_token'
        session.save()

        # Send mismatched state
        response = self.client.get(reverse('gmail:callback'), {
            'code': 'valid_mock_code',
            'state': 'attacker_manipulated_state'
        })
        self.assertEqual(response.status_code, 302)
        # Verify account was not created
        self.assertFalse(GmailAccount.objects.filter(user=self.user).exists())

    @patch('gmail_integration.oauth.GmailOAuthHandler.exchange_code_for_tokens')
    def test_oauth_callback_success_mocked(self, mock_exchange):
        """Callback with valid state exchanges code and creates connected GmailAccount"""
        mock_exchange.return_value = {
            'email': 'authorized.user@gmail.com',
            'access_token': 'mock_valid_access_token',
            'refresh_token': 'mock_valid_refresh_token',
            'scopes': 'https://www.googleapis.com/auth/gmail.readonly',
        }

        # Set matching state in session
        session = self.client.session
        session['gmail_oauth_state'] = 'secure_expected_state_token'
        session.save()

        response = self.client.get(reverse('gmail:callback'), {
            'code': 'mock_authorization_code',
            'state': 'secure_expected_state_token'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/', response.url)

        account = GmailAccount.objects.filter(user=self.user, email_address='authorized.user@gmail.com').first()
        self.assertIsNotNone(account)
        self.assertTrue(account.is_connected)
        self.assertTrue(account.is_active)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.is_google_connected)

    def test_disconnect_account_post_only(self):
        """Disconnect endpoint rejects GET requests and enforces POST"""
        account = GmailAccount.objects.create(
            user=self.user,
            email_address='to_disconnect@gmail.com',
            is_connected=True,
            is_active=True
        )
        # GET should be rejected (405 Method Not Allowed)
        get_response = self.client.get(reverse('gmail:disconnect'))
        self.assertEqual(get_response.status_code, 405)

        # POST disconnects account
        post_response = self.client.post(reverse('gmail:disconnect'), {
            'account_id': account.id
        })
        self.assertEqual(post_response.status_code, 302)

        account.refresh_from_db()
        self.assertFalse(account.is_connected)
        self.assertFalse(account.is_active)

    def test_cross_user_disconnect_prevention(self):
        """User B cannot disconnect User A's GmailAccount"""
        user_b = User.objects.create_user(
            username='attacker_b',
            email='attacker@example.com',
            password='Password123!'
        )
        account_a = GmailAccount.objects.create(
            user=self.user,
            email_address='victim@gmail.com',
            is_connected=True,
            is_active=True
        )

        # Log in as User B and attempt to disconnect User A's account
        client_b = Client()
        client_b.force_login(user_b)
        response = client_b.post(reverse('gmail:disconnect'), {
            'account_id': account_a.id
        })
        self.assertEqual(response.status_code, 302)

        # Verify User A's account remains connected
        account_a.refresh_from_db()
        self.assertTrue(account_a.is_connected)

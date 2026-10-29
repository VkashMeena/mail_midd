import logging
from datetime import timedelta
from django.utils import timezone
from .models import GmailAccount
from .oauth import GmailOAuthHandler
from .client import GmailClient
from .exceptions import (
    GmailIntegrationError,
    GmailConfigurationError,
    GmailOAuthError,
    GmailTokenError,
    GmailPermissionError,
    GmailAPIError
)

logger = logging.getLogger(__name__)

# State constants
STATE_NOT_CONNECTED = 'NOT_CONNECTED'
STATE_CONNECTED = 'CONNECTED'
STATE_TOKEN_EXPIRED = 'TOKEN_EXPIRED'
STATE_PERMISSION_ERROR = 'PERMISSION_ERROR'
STATE_CONNECTION_ERROR = 'CONNECTION_ERROR'


class GmailService:
    def __init__(self, oauth_handler=None):
        self.oauth_handler = oauth_handler or GmailOAuthHandler()

    def get_active_account(self, user):
        """
        Retrieves the primary active connected Gmail account for a user.
        Always user-isolated via user=user.
        """
        if not user.is_authenticated:
            return None
        return GmailAccount.objects.filter(user=user, is_connected=True, is_active=True).first()

    def get_account_status(self, user) -> dict:
        """
        Computes user-facing connection state for settings and dashboard.
        Mapped states:
        - NOT_CONNECTED
        - CONNECTED
        - TOKEN_EXPIRED
        - PERMISSION_ERROR
        - CONNECTION_ERROR
        """
        if not user.is_authenticated:
            return {
                'state': STATE_NOT_CONNECTED,
                'status': 'not_connected',
                'badge_class': 'bg-secondary-subtle text-secondary',
                'label': 'Not Connected',
                'account': None,
                'email': None,
                'connected_at': None,
                'last_synced': None,
                'has_read_permission': False,
                'has_send_permission': False,
                'can_send': False,
            }

        # Check for any account for this user
        account = self.get_active_account(user)
        if not account:
            # Check if there is a disconnected or expired account to report proper status
            any_account = GmailAccount.objects.filter(user=user).order_by('-updated_at').first()
            if any_account and not any_account.is_connected and any_account.encrypted_access_token:
                return {
                    'state': STATE_TOKEN_EXPIRED,
                    'status': 'expired',
                    'badge_class': 'bg-warning-subtle text-warning border border-warning-subtle',
                    'label': 'Reauthorization Required',
                    'account': any_account,
                    'email': any_account.email_address,
                    'connected_at': any_account.last_connected_at,
                    'last_synced': any_account.last_synced_at or "Not synchronized yet",
                    'has_read_permission': any_account.has_read_permission,
                    'has_send_permission': any_account.has_send_permission,
                    'can_send': any_account.has_send_permission,
                }

            return {
                'state': STATE_NOT_CONNECTED,
                'status': 'not_connected',
                'badge_class': 'bg-secondary-subtle text-secondary',
                'label': 'Not Connected',
                'account': None,
                'email': None,
                'connected_at': None,
                'last_synced': None,
                'has_read_permission': False,
                'has_send_permission': False,
                'can_send': False,
            }

        # If connected, verify token validity
        if account.token_expiry and account.token_expiry < timezone.now():
            if not account.encrypted_refresh_token:
                account.is_connected = False
                account.save(update_fields=['is_connected'])
                return {
                    'state': STATE_TOKEN_EXPIRED,
                    'status': 'expired',
                    'badge_class': 'bg-warning-subtle text-warning border border-warning-subtle',
                    'label': 'Reauthorization Required',
                    'account': account,
                    'email': account.email_address,
                    'connected_at': account.last_connected_at,
                    'last_synced': account.last_synced_at or "Not synchronized yet",
                    'has_read_permission': account.has_read_permission,
                    'has_send_permission': account.has_send_permission,
                    'can_send': account.has_send_permission,
                }

        return {
            'state': STATE_CONNECTED,
            'status': 'connected',
            'badge_class': 'bg-success-subtle text-success border border-success-subtle',
            'label': 'Connected',
            'account': account,
            'email': account.email_address,
            'connected_at': account.last_connected_at,
            'last_synced': account.last_synced_at or "Not synchronized yet",
            'has_read_permission': account.has_read_permission,
            'has_send_permission': account.has_send_permission,
            'can_send': account.has_send_permission,
        }

    def connect_gmail_account(self, user, auth_code: str, incoming_state: str, session_state: str) -> GmailAccount:
        """
        Completes the OAuth flow:
        1. Validates CSRF state against session
        2. Exchanges auth code for tokens with Google
        3. Fetches authenticated Google email profile (does NOT trust frontend input)
        4. Updates or creates GmailAccount (encrypting tokens)
        5. Preserves existing refresh token if Google does not return a new one
        6. Updates user profile status
        """
        if not self.oauth_handler.validate_callback_state(incoming_state, session_state):
            logger.warning("OAuth state verification mismatch for user %s", user)
            raise GmailOAuthError("Invalid authorization request.")

        # Exchange code for tokens
        token_data = self.oauth_handler.exchange_code_for_tokens(auth_code)
        access_token = token_data.get('access_token')
        new_refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in', 3600)
        scopes = token_data.get('scope', '')

        # Check if email is already provided in token_data (e.g., from mock or id_token),
        # otherwise fetch authenticated profile directly from Gmail API
        email_address = token_data.get('email')
        if not email_address:
            client = GmailClient(access_token=access_token, refresh_token=new_refresh_token)
            profile = client.get_profile()
            email_address = profile.get('emailAddress', '').strip().lower()
        else:
            email_address = email_address.strip().lower()

        if not email_address:
            raise GmailOAuthError("Unable to retrieve email address identity from Google authorization.")

        # Deactivate other active accounts for this user to enforce single-active primary account
        GmailAccount.objects.filter(user=user).update(is_active=False)

        # Check if account already exists for reconnect flow
        account = GmailAccount.objects.filter(user=user, email_address=email_address).first()
        now = timezone.now()
        expiry_dt = now + timedelta(seconds=expires_in)

        if account:
            # Reconnect existing account: update tokens, preserve refresh_token if new one omitted
            account.set_access_token(access_token)
            if new_refresh_token:
                account.set_refresh_token(new_refresh_token)
            # If new_refresh_token is None/empty, the existing refresh_token remains intact in DB!
            account.token_expiry = expiry_dt
            account.scopes = scopes
            account.is_connected = True
            account.is_active = True
            account.last_connected_at = now
            account.save()
            logger.info("Gmail OAuth completed for existing account %s", account.email_address)
        else:
            # Create new account with encrypted tokens
            account = GmailAccount(
                user=user,
                email_address=email_address,
                provider='google',
                is_connected=True,
                is_active=True,
                token_expiry=expiry_dt,
                scopes=scopes,
                last_connected_at=now
            )
            account.set_access_token(access_token)
            if new_refresh_token:
                account.set_refresh_token(new_refresh_token)
            account.save()
            logger.info("Gmail OAuth completed for new account %s", account.email_address)

        # Update UserProfile flag
        if hasattr(user, 'profile'):
            user.profile.is_google_connected = True
            user.profile.save(update_fields=['is_google_connected'])

        return account

    def disconnect_gmail_account(self, user, account_id=None) -> bool:
        """
        Safely disconnects Gmail account:
        1. Validates ownership (user=user)
        2. Remotely revokes credentials on Google servers (graceful on failure)
        3. Marks is_connected=False, is_active=False
        4. Keeps local emails and database records intact
        """
        qs = GmailAccount.objects.filter(user=user)
        if account_id:
            qs = qs.filter(id=account_id)

        account = qs.first()
        if not account:
            return False

        # Attempt remote revocation on Google servers
        try:
            client = GmailClient(account=account)
            client.revoke_credentials()
        except Exception as exc:
            logger.warning("Revocation during disconnect encountered exception: %s", exc)

        account.is_connected = False
        account.is_active = False
        account.save(update_fields=['is_connected', 'is_active', 'updated_at'])

        # Update UserProfile flag
        if hasattr(user, 'profile'):
            user.profile.is_google_connected = False
            user.profile.save(update_fields=['is_google_connected'])

        logger.info("Gmail account disconnected for user %s", user)
        return True

    def get_authenticated_gmail_service(self, user):
        """
        Returns authenticated Google API client service for the user's active account.
        Views should use this rather than calling build('gmail', ...) directly.
        """
        account = self.get_active_account(user)
        if not account:
            raise GmailIntegrationError("No active connected Gmail account found.")
        client = GmailClient(account=account)
        return client.build_service()

    def get_gmail_profile(self, user) -> dict:
        """
        Retrieves user's Gmail profile from API.
        """
        account = self.get_active_account(user)
        if not account:
            raise GmailIntegrationError("No active connected Gmail account found.")
        client = GmailClient(account=account)
        return client.get_profile()

    def refresh_gmail_credentials(self, user, account_id=None) -> bool:
        """
        Forces an access token refresh using the account's refresh token.
        """
        qs = GmailAccount.objects.filter(user=user)
        if account_id:
            qs = qs.filter(id=account_id)
        account = qs.first()
        if not account:
            raise GmailIntegrationError("No Gmail account found to refresh.")
        client = GmailClient(account=account)
        return client.refresh_access_token()

    # Backwards compatibility aliases
    connect_account = connect_gmail_account
    disconnect_account = disconnect_gmail_account

    # Placeholders for Phase 4 synchronization
    def list_messages(self, user):
        raise NotImplementedError("Gmail message synchronization will be active in Phase 4.")

    def get_message(self, user, message_id):
        raise NotImplementedError("Gmail message retrieval will be active in Phase 4.")

    def sync_messages(self, user):
        raise NotImplementedError("Gmail message synchronization will be active in Phase 4.")


gmail_service = GmailService()

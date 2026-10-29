import secrets
import logging
from urllib.parse import urlencode
import requests
from django.conf import settings
from .scopes import get_scopes_list
from .exceptions import (
    GmailConfigurationError,
    GmailOAuthError,
    GmailAuthenticationError,
    GmailAPIError
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

class GmailOAuthHandler:
    def __init__(self, client_id=None, client_secret=None, redirect_uri=None, scopes=None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes

    @property
    def client_id(self):
        return self._client_id or getattr(settings, 'GOOGLE_CLIENT_ID', '')

    @property
    def client_secret(self):
        return self._client_secret or getattr(settings, 'GOOGLE_CLIENT_SECRET', '')

    @property
    def redirect_uri(self):
        return self._redirect_uri or getattr(
            settings, 'GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8000/gmail/oauth/callback/'
        )

    @property
    def scopes(self):
        return self._scopes or get_scopes_list()

    def is_configured(self) -> bool:
        """Checks if all required OAuth configuration settings are present."""
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.scopes)

    def generate_state(self) -> str:
        """Generates a cryptographically secure random token for state CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scopes=None) -> str:
        """
        Builds Google OAuth 2.0 authorization URL with CSRF state protection.
        Does not accept client_id, redirect_uri, or scopes from frontend parameters.
        Optional scopes parameter allows requesting extended permissions (e.g. Gmail send).
        """
        if not self.is_configured():
            logger.warning("OAuth authorization attempt failed: Gmail integration is not configured.")
            raise GmailConfigurationError("Gmail integration is not configured.")

        requested_scopes = scopes or self.scopes
        scope_str = ' '.join(requested_scopes) if isinstance(requested_scopes, (list, tuple, set)) else str(requested_scopes)

        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': scope_str,
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
            'include_granted_scopes': 'true',
        }
        logger.info("Gmail OAuth started")
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def validate_callback_state(self, incoming_state: str, session_state: str) -> bool:
        """
        Validates state against session using constant-time comparison to prevent CSRF attacks.
        """
        if not incoming_state or not session_state:
            return False
        return secrets.compare_digest(str(incoming_state), str(session_state))

    def exchange_code_for_tokens(self, auth_code: str) -> dict:
        """
        Exchanges authorization code for Google OAuth tokens.
        Never logs authorization codes, access tokens, or refresh tokens.
        """
        if not self.is_configured():
            raise GmailConfigurationError("Gmail integration is not configured.")

        if not auth_code:
            raise GmailOAuthError("Authorization code is missing.")

        payload = {
            'code': auth_code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'authorization_code',
        }

        try:
            response = requests.post(GOOGLE_TOKEN_URL, data=payload, timeout=15)
            data = response.json()
        except requests.RequestException as exc:
            logger.error("Network error during token exchange with Google: %s", exc)
            raise GmailAPIError("Unable to communicate with Gmail authorization servers.")
        except Exception as exc:
            logger.error("Unexpected error during token exchange: %s", exc)
            raise GmailOAuthError("Unable to complete Gmail authorization.")

        if response.status_code != 200:
            error_code = data.get('error', 'unknown')
            error_desc = data.get('error_description', '')
            logger.warning("Google token exchange failed: %s (%s)", error_code, error_desc)
            if error_code in ('invalid_grant', 'invalid_request'):
                raise GmailOAuthError("Invalid or expired authorization code. Please initiate connection again.")
            raise GmailOAuthError("Unable to complete Gmail authorization.")

        access_token = data.get('access_token')
        if not access_token:
            raise GmailOAuthError("Google did not return an access token.")

        return {
            'access_token': access_token,
            'refresh_token': data.get('refresh_token'),  # Note: Can be None if already authorized previously
            'expires_in': data.get('expires_in', 3600),
            'scope': data.get('scope', ' '.join(self.scopes)),
            'token_type': data.get('token_type', 'Bearer'),
        }

import logging
from datetime import timedelta
import requests
from django.utils import timezone
from django.conf import settings
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .scopes import get_scopes_list
from .exceptions import (
    GmailIntegrationError,
    GmailTokenError,
    GmailPermissionError,
    GmailAPIError
)

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

class GmailClient:
    """
    Encapsulates Google API credentials management, token refreshing,
    and Gmail API service construction.
    Views must never call Google APIs or build services directly.
    """

    def __init__(self, account=None, access_token=None, refresh_token=None, scopes=None, client_id=None, client_secret=None):
        self.account = account
        self._client_id = client_id
        self._client_secret = client_secret
        self.scopes = scopes or get_scopes_list()

        # Decrypt tokens from account if provided
        if account:
            self._access_token = account.get_access_token()
            self._refresh_token = account.get_refresh_token()
            if account.scopes:
                self.scopes = account.scopes.split()
        else:
            self._access_token = access_token
            self._refresh_token = refresh_token

        self._credentials = None
        self._service = None

    @property
    def client_id(self):
        return self._client_id or getattr(settings, 'GOOGLE_CLIENT_ID', '')

    @property
    def client_secret(self):
        return self._client_secret or getattr(settings, 'GOOGLE_CLIENT_SECRET', '')

    def get_credentials(self) -> Credentials:
        """
        Builds and validates google.oauth2.credentials.Credentials.
        Refreshes the token automatically if expired.
        """
        if not self._credentials:
            self._credentials = Credentials(
                token=self._access_token,
                refresh_token=self._refresh_token,
                token_uri=GOOGLE_TOKEN_URI,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=self.scopes
            )

        # Check if access token needs refresh
        if self._credentials.expired or not self._credentials.valid:
            self.refresh_access_token()

        return self._credentials

    def refresh_access_token(self) -> bool:
        """
        Refreshes expired access token using stored refresh token.
        Updates encrypted token on account in database automatically.
        """
        if not self._refresh_token:
            logger.warning("Token refresh failed: No refresh token present on account.")
            if self.account:
                self.account.is_connected = False
                self.account.save(update_fields=['is_connected'])
            raise GmailTokenError("Your Gmail connection needs to be reauthorized. (Missing refresh token)")

        try:
            request = Request()
            if not self._credentials:
                self._credentials = Credentials(
                    token=self._access_token,
                    refresh_token=self._refresh_token,
                    token_uri=GOOGLE_TOKEN_URI,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=self.scopes
                )
            self._credentials.refresh(request)
            new_token = self._credentials.token

            if self.account and new_token:
                self.account.set_access_token(new_token)
                self.account.token_expiry = timezone.now() + timedelta(hours=1)
                self.account.is_connected = True
                self.account.save(update_fields=['encrypted_access_token', 'token_expiry', 'is_connected'])
                logger.info("Successfully refreshed Gmail access token for account id=%s", self.account.id)
            self._access_token = new_token
            return True
        except Exception as exc:
            logger.error("Token refresh failed with Google: %s", exc)
            if self.account:
                self.account.is_connected = False
                self.account.save(update_fields=['is_connected'])
            raise GmailTokenError("Your Gmail connection needs to be reauthorized. Please reconnect.")

    def build_service(self):
        """
        Constructs authenticated Google API service client.
        """
        if self._service:
            return self._service

        credentials = self.get_credentials()
        try:
            self._service = build('gmail', 'v1', credentials=credentials, cache_discovery=False)
            return self._service
        except Exception as exc:
            logger.error("Failed to build Gmail API service: %s", exc)
            raise GmailAPIError("Unable to initialize Gmail service client.")

    def get_profile(self) -> dict:
        """
        Retrieves the authenticated Gmail profile from Google.
        Extracts verified Google email address.
        """
        service = self.build_service()
        try:
            profile = service.users().getProfile(userId='me').execute()
            return profile
        except HttpError as exc:
            logger.error("Gmail profile API returned HTTP error: %s", exc)
            if exc.resp.status in (401, 403):
                raise GmailPermissionError("Gmail permission could not be established.")
            raise GmailAPIError("Unable to communicate with Gmail servers.")
        except Exception as exc:
            logger.error("Unexpected error retrieving Gmail profile: %s", exc)
            raise GmailAPIError("Unable to retrieve Gmail profile.")

    def revoke_credentials(self) -> bool:
        """
        Remotely revokes credentials on Google servers during account disconnect.
        Gracefully handles network errors or already revoked tokens.
        """
        token = self._refresh_token or self._access_token
        if not token:
            return True

        try:
            response = requests.post(
                GOOGLE_REVOKE_URL,
                params={'token': token},
                headers={'content-type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Successfully revoked Google OAuth credentials remotely.")
                return True
            else:
                logger.warning("Google token revocation returned non-200 status: %s", response.status_code)
                return False
        except Exception as exc:
            logger.warning("Remote token revocation encountered error (ignored): %s", exc)
            return False

"""
Custom Exception Classes for Gmail Integration.
Provides consistent, user-safe error messages throughout the OAuth and API lifecycle.
"""

class GmailIntegrationError(Exception):
    """Base exception for all Gmail integration errors with a user-friendly message."""
    default_message = "An error occurred with Gmail integration. Please try again."

    def __init__(self, message=None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message


class GmailConfigurationError(GmailIntegrationError):
    """Raised when required Google OAuth settings or environment variables are missing."""
    default_message = "Gmail integration is not configured."


class GmailOAuthError(GmailIntegrationError):
    """Raised when OAuth handshake, callback, or state validation fails."""
    default_message = "Unable to complete Gmail authorization."


# Backward compatibility alias for Phase 2 code/tests
GmailAuthenticationError = GmailOAuthError


class GmailTokenError(GmailIntegrationError):
    """Raised when access token or refresh token is invalid, expired, or cannot be refreshed."""
    default_message = "Your Gmail connection needs to be reauthorized."


class GmailPermissionError(GmailIntegrationError):
    """Raised when user denies requested Gmail scopes or insufficient permissions are granted."""
    default_message = "Gmail permission could not be established."


class GmailAPIError(GmailIntegrationError):
    """Raised when Google API returns an error status or network error occurs."""
    default_message = "Unable to communicate with Gmail servers. Please try again later."

"""
Centralized Gmail and Google OAuth Scopes for AI Smart Mail Manager.
In Phase 3, we requested strictly read-only permissions.
In Phase 7, Gmail sending/reply permissions are explicitly configured via an opt-in flow;
existing read-only permissions are NEVER silently escalated.
"""

GMAIL_READ_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
GMAIL_SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
USERINFO_EMAIL_SCOPE = 'https://www.googleapis.com/auth/userinfo.email'

# Core required Gmail OAuth scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
]

GMAIL_READ_SCOPES = [
    GMAIL_READ_SCOPE,
    USERINFO_EMAIL_SCOPE,
]

GMAIL_FULL_SCOPES = [
    GMAIL_READ_SCOPE,
    GMAIL_SEND_SCOPE,
    USERINFO_EMAIL_SCOPE,
]

# Standard scopes include both reading and sending permissions
GMAIL_SCOPES = GMAIL_FULL_SCOPES


def get_scopes_list(include_send: bool = True):
    """Returns the list of OAuth scopes. By default, includes both read and send scopes."""
    if include_send:
        return list(GMAIL_FULL_SCOPES)
    return list(GMAIL_READ_SCOPES)


def get_send_scopes_list():
    """Returns the full scope set including Gmail send permissions."""
    return list(GMAIL_FULL_SCOPES)


def get_scopes_string(include_send: bool = True):
    """Returns a space-separated string of OAuth scopes."""
    return ' '.join(get_scopes_list(include_send=include_send))


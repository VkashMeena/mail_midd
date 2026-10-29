import logging
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import gmail_service
from .sync import sync_service
from .exceptions import (
    GmailIntegrationError,
    GmailConfigurationError,
    GmailOAuthError,
    GmailPermissionError,
    GmailTokenError,
    GmailAPIError
)

logger = logging.getLogger(__name__)

REDIRECT_TARGET = 'settings_gmail'


@login_required
def connect_view(request):
    """
    Initiates Google OAuth 2.0 flow for Gmail integration.
    Saves cryptographically generated state in session to prevent CSRF.
    Does not accept client_id, redirect_uri, or scopes from frontend parameters.
    """
    oauth_handler = gmail_service.oauth_handler
    if not oauth_handler.is_configured():
        messages.error(request, "Gmail integration is not configured.")
        return redirect(REDIRECT_TARGET)

    state = oauth_handler.generate_state()
    request.session['gmail_oauth_state'] = state
    try:
        auth_url = oauth_handler.get_authorization_url(state)
        return redirect(auth_url)
    except GmailConfigurationError as exc:
        messages.error(request, exc.message)
        return redirect(REDIRECT_TARGET)
    except Exception as exc:
        logger.error("Failed to generate authorization URL: %s", exc)
        messages.error(request, "Gmail integration is not configured.")
        return redirect(REDIRECT_TARGET)


@login_required
def authorize_send_view(request):
    """
    Explicit opt-in OAuth flow to authorize Gmail Send permissions.
    Preserves read-only scopes by requesting GMAIL_FULL_SCOPES.
    """
    oauth_handler = gmail_service.oauth_handler
    if not oauth_handler.is_configured():
        messages.error(request, "Gmail integration is not configured.")
        return redirect(REDIRECT_TARGET)

    from .scopes import get_send_scopes_list
    state = oauth_handler.generate_state()
    request.session['gmail_oauth_state'] = state
    try:
        auth_url = oauth_handler.get_authorization_url(state, scopes=get_send_scopes_list())
        return redirect(auth_url)
    except Exception as exc:
        logger.error("Failed to generate send authorization URL: %s", exc)
        messages.error(request, "Unable to initiate Gmail send authorization.")
        return redirect(REDIRECT_TARGET)



@login_required
def callback_view(request):
    """
    Handles Google OAuth 2.0 callback with state verification and code exchange.
    Redirects safely to /settings/gmail/ with user-friendly alerts.
    Never exposes authorization codes, tokens, or raw Google error details.
    """
    error = request.GET.get('error')
    if error:
        logger.warning("Google OAuth denied or returned error: %s", error)
        if error in ('access_denied', 'user_denied'):
            messages.error(request, "Google authorization was cancelled.")
        else:
            messages.error(request, "Unable to complete Gmail authorization.")
        return redirect(REDIRECT_TARGET)

    incoming_code = request.GET.get('code')
    incoming_state = request.GET.get('state')
    session_state = request.session.pop('gmail_oauth_state', None)

    if not incoming_code or not incoming_state or not session_state:
        messages.error(request, "Unable to complete Gmail authorization.")
        return redirect(REDIRECT_TARGET)

    try:
        account = gmail_service.connect_gmail_account(
            user=request.user,
            auth_code=incoming_code,
            incoming_state=incoming_state,
            session_state=session_state
        )
        try:
            stats = sync_service.sync_gmail_account(account)
            messages.success(
                request,
                f"Your Gmail account ({account.email_address}) has been connected and synchronized! "
                f"Fetched {stats.get('created', 0)} new emails."
            )
        except Exception as sync_exc:
            logger.error("Initial Gmail sync failed after connect for %s: %s", account.email_address, sync_exc)
            messages.success(request, f"Your Gmail account has been connected successfully: {account.email_address}")

        return redirect(REDIRECT_TARGET)
    except GmailOAuthError as exc:
        logger.warning("Gmail OAuth error during callback: %s", exc)
        messages.error(request, exc.message)
    except GmailPermissionError as exc:
        logger.warning("Gmail permission error during callback: %s", exc)
        messages.error(request, exc.message)
    except GmailAPIError as exc:
        logger.error("Gmail API error during callback: %s", exc)
        messages.error(request, exc.message)
    except GmailIntegrationError as exc:
        messages.error(request, exc.message)
    except Exception as exc:
        logger.exception("Unexpected error during Gmail OAuth callback: %s", exc)
        messages.error(request, "Unable to complete Gmail authorization.")

    return redirect(REDIRECT_TARGET)


@login_required
@require_POST
def disconnect_view(request):
    """
    Disconnects active Gmail account for current user.
    Strictly user-scoped. Historical emails remain preserved.
    """
    account_id = request.POST.get('account_id')
    success = gmail_service.disconnect_gmail_account(user=request.user, account_id=account_id)
    if success:
        messages.success(request, "Gmail account disconnected successfully. Your existing email history remains preserved.")
    else:
        messages.info(request, "No active Gmail connection found to disconnect.")
    return redirect(REDIRECT_TARGET)


@login_required
@require_POST
def sync_view(request):
    """
    Triggers real Gmail email synchronization for current user's connected account.
    Strictly user-isolated and requires POST + CSRF.
    """
    account = gmail_service.get_active_account(request.user)
    if not account:
        messages.warning(request, "No connected Gmail account found to synchronize.")
        return redirect('settings_gmail')

    try:
        stats = sync_service.sync_gmail_account(account)
        messages.success(
            request,
            f"Gmail Sync Complete: {stats['fetched']} fetched, {stats['created']} new, {stats['updated']} updated."
        )
    except GmailTokenError as exc:
        logger.warning("Token expired during sync for user %s: %s", request.user, exc)
        messages.error(request, "Your Gmail connection needs to be renewed. Please reconnect your account.")
        return redirect('settings_gmail')
    except GmailIntegrationError as exc:
        logger.error("Gmail integration error during sync: %s", exc)
        messages.error(request, "Unable to synchronize your Gmail account right now.")
    except Exception as exc:
        logger.exception("Unexpected error during Gmail sync: %s", exc)
        messages.error(request, "Unable to synchronize your Gmail account right now.")

    return redirect('inbox')


@login_required
def gmail_account_view(request):
    """
    Dedicated Gmail Account page at /settings/gmail/.
    Displays connection status, authenticated email, connection date,
    security notice, sync logs, and connect/disconnect controls.
    """
    status_data = gmail_service.get_account_status(request.user)
    account = status_data.get('account')
    recent_sync_logs = account.sync_logs.order_by('-started_at')[:5] if account else []

    context = {
        'page_title': 'Gmail Account Settings',
        'status_data': status_data,
        'account': account,
        'is_connected': status_data.get('status') == 'connected',
        'recent_sync_logs': recent_sync_logs,
    }
    return render(request, 'gmail_account.html', context)


@login_required
def status_api_view(request):
    """
    Returns current user's Gmail connection status as JSON.
    Never exposes raw tokens, secrets, or internal credential objects.
    """
    from django.urls import reverse
    status_data = gmail_service.get_account_status(request.user)
    return JsonResponse({
        'status': status_data['status'],
        'state': status_data['state'],
        'label': status_data['label'],
        'email': status_data['email'],
        'has_read_permission': status_data.get('has_read_permission', False),
        'has_send_permission': status_data.get('has_send_permission', False),
        'can_send': status_data.get('can_send', False),
        'grant_send_url': reverse('gmail:authorize_send'),
        'connected_at': str(status_data['connected_at']) if status_data.get('connected_at') else None,
        'last_synced': str(status_data['last_synced']) if status_data.get('last_synced') else None
    })

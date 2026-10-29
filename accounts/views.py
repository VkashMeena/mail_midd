import logging
import requests
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth import login, logout, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

from .forms import (
    UserLoginForm,
    UserRegistrationForm,
    UserProfileEditForm,
    CustomPasswordChangeForm
)
from .models import UserProfile

def login_view(request):
    """
    Real authentication view supporting email or username login.
    Redirects to dashboard or next url upon success.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            remember_me = form.cleaned_data.get('remember_me')
            if not remember_me:
                request.session.set_expiry(0)
            messages.success(request, f"Welcome back, {user.profile.get_display_name() if hasattr(user, 'profile') else user.username}!")
            next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard:index'
            return redirect(next_url)
        else:
            messages.error(request, "Invalid email or password.")
    else:
        form = UserLoginForm()

    context = {
        'form': form,
        'google_enabled': bool(getattr(settings, 'GOOGLE_CLIENT_ID', '') or getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')),
        'next': request.GET.get('next', ''),
    }
    return render(request, 'auth/login.html', context)


def register_view(request):
    """
    Real user registration view with email validation and password confirmation.
    Redirects to /login/ with 'Account created successfully.' message upon completion.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, "Account created successfully. Please sign in with your credentials.")
            return redirect('accounts:login')
        else:
            messages.error(request, "Please correct the registration errors below.")
    else:
        form = UserRegistrationForm()

    context = {
        'form': form,
        'google_enabled': bool(getattr(settings, 'GOOGLE_CLIENT_ID', '') or getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')),
    }
    return render(request, 'auth/register.html', context)


def logout_view(request):
    """
    Logs out user and clears active session.
    Redirects to /login/.
    """
    logout(request)
    messages.info(request, "You have been logged out securely.")
    return redirect('accounts:login')


@login_required
def profile_view(request):
    """
    User Profile management view displaying photo, name, email, timezone, and theme.
    Allows editing display name, timezone, theme, and uploading profile avatar.
    Email is strictly read-only.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserProfileEditForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Unable to save profile changes. Please check the errors below.")
    else:
        form = UserProfileEditForm(instance=profile)

    context = {
        'page_title': 'User Profile',
        'profile': profile,
        'form': form,
    }
    return render(request, 'profile.html', context)


@login_required
def password_change_view(request):
    """
    Secure password change view using Django PasswordChangeForm.
    Maintains session authentication hash upon success.
    """
    if request.method == 'POST':
        form = CustomPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Your password has been changed successfully.")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Please correct the errors in the password form.")
    else:
        form = CustomPasswordChangeForm(user=request.user)

    context = {
        'page_title': 'Change Password',
        'form': form,
    }
    return render(request, 'auth/password_change.html', context)


@login_required
def account_delete_view(request):
    """
    Account deletion confirmation foundation.
    Requires explicit POST confirmation.
    """
    if request.method == 'POST':
        user = request.user
        logout(request)
        user.delete()
        messages.info(request, "Your account has been deleted permanently.")
        return redirect('accounts:login')

    return redirect('dashboard:settings')


def google_login_view(request):
    """
    Initiates Google OAuth 2.0 flow for authentication.
    """
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
    redirect_uri = getattr(settings, 'GOOGLE_OAUTH_REDIRECT_URI', '') or request.build_absolute_uri(reverse('accounts:google_callback'))

    if not client_id:
        messages.warning(
            request,
            "Google Sign-In is ready! To activate real Google OAuth, set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in your .env file."
        )
        return redirect('accounts:login')

    state = secrets.token_urlsafe(32)
    request.session['google_login_state'] = state

    auth_params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
        'include_granted_scopes': 'true',
    }
    logger.info("Initiating Google OAuth login flow (redirect_uri=%s)", redirect_uri)
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(auth_params)}"
    return redirect(google_auth_url)


def google_callback_view(request):
    """
    Callback endpoint for Google OAuth authorization code.
    Exchanges code for tokens, retrieves user profile, authenticates/creates User,
    and links Gmail account.
    """
    code = request.GET.get('code')
    error = request.GET.get('error')
    incoming_state = request.GET.get('state')
    session_state = request.session.pop('google_login_state', None)

    if error:
        messages.error(request, f"Google Authentication cancelled or failed: {error}")
        return redirect('accounts:login')

    if not code:
        messages.warning(request, "No authorization code received from Google.")
        return redirect('accounts:login')

    if session_state and incoming_state and session_state != incoming_state:
        messages.error(request, "Security verification failed: OAuth state mismatch.")
        return redirect('accounts:login')

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '') or getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
    redirect_uri = getattr(settings, 'GOOGLE_OAUTH_REDIRECT_URI', '') or request.build_absolute_uri(reverse('accounts:google_callback'))

    if not client_id or not client_secret:
        messages.error(request, "Google OAuth credentials not configured in settings.")
        return redirect('accounts:login')

    # Exchange authorization code for tokens
    try:
        token_resp = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=15
        )
        if token_resp.status_code != 200:
            err_data = token_resp.json() if 'application/json' in token_resp.headers.get('content-type', '') else {}
            err_msg = err_data.get('error_description') or err_data.get('error') or f"HTTP {token_resp.status_code}"
            messages.error(request, f"Google authorization failed: {err_msg}")
            return redirect('accounts:login')

        tokens = token_resp.json()
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')

        # Retrieve user profile from Google
        userinfo_resp = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=15
        )
        if userinfo_resp.status_code != 200:
            messages.error(request, "Failed to retrieve user profile from Google.")
            return redirect('accounts:login')

        user_info = userinfo_resp.json()
        email = user_info.get('email')
        if not email:
            messages.error(request, "Google account did not return a verified email address.")
            return redirect('accounts:login')

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()

        if not user:
            # Create user if account doesn't exist yet
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            first_name = user_info.get('given_name', '')
            last_name = user_info.get('family_name', '')
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            user.set_unusable_password()
            user.save()

        # Log user into Django session
        login(request, user, backend='accounts.backends.EmailOrUsernameModelBackend')

        # Connect or update GmailAccount with encrypted tokens
        account = None
        try:
            from gmail_integration.models import GmailAccount

            expires_in = tokens.get('expires_in', 3600)
            expiry_dt = timezone.now() + timedelta(seconds=expires_in)
            granted_scopes = tokens.get('scope', 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email')

            # Ensure single active account per user
            GmailAccount.objects.filter(user=user).exclude(email_address=email).update(is_active=False)

            account = GmailAccount.objects.filter(user=user, email_address=email).first()
            if not account:
                account = GmailAccount(
                    user=user,
                    email_address=email,
                    provider='google'
                )

            account.is_connected = True
            account.is_active = True
            account.token_expiry = expiry_dt
            account.scopes = granted_scopes
            account.last_connected_at = timezone.now()

            # Set tokens cleanly: set_access_token/set_refresh_token handle encryption internally
            if access_token:
                account.set_access_token(access_token)
            if refresh_token:
                account.set_refresh_token(refresh_token)

            account.save()
            logger.info("Gmail account linked successfully for user %s (%s)", user.username, email)

            # Update UserProfile flag
            if hasattr(user, 'profile'):
                user.profile.is_google_connected = True
                user.profile.save(update_fields=['is_google_connected'])
        except Exception as link_exc:
            logger.error("Error linking Gmail account during Google OAuth callback: %s", link_exc, exc_info=True)

        # Check if user granted Gmail read permission (Granular Consent support)
        has_gmail_permission = any('gmail.readonly' in s for s in granted_scopes.split())

        sync_stats = None
        if account and has_gmail_permission:
            try:
                from gmail_integration.sync import sync_service
                logger.info("Initiating automatic initial Gmail sync for %s", email)
                sync_stats = sync_service.sync_gmail_account(account)
                logger.info("Automatic initial Gmail sync completed for %s: %s", email, sync_stats)
            except Exception as sync_exc:
                logger.error("Initial Gmail sync failed during Google login for %s: %s", email, sync_exc, exc_info=True)

        if not has_gmail_permission:
            messages.warning(
                request,
                f"Welcome, {user.get_full_name() or user.email}! You are signed in, but Gmail read permission was not granted. "
                f"To view and synchronize your emails, please connect Gmail in Settings."
            )
        elif sync_stats and sync_stats.get('created', 0) > 0:
            messages.success(
                request,
                f"Welcome, {user.get_full_name() or user.email}! Synchronized {sync_stats['created']} emails from your Gmail inbox."
            )
        elif sync_stats:
            messages.success(
                request,
                f"Welcome, {user.get_full_name() or user.email}! Signed in with Google. Your Gmail inbox is synchronized ({sync_stats.get('fetched', 0)} checked)."
            )
        else:
            messages.info(
                request,
                f"Welcome, {user.get_full_name() or user.email}! Signed in with Google. Your Gmail account is connected."
            )

        return redirect('inbox')

    except Exception as exc:
        messages.error(request, f"Unexpected error during Google sign-in: {str(exc)}")
        return redirect('accounts:login')

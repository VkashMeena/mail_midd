from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from .services import get_dashboard_stats
from accounts.forms import UserProfileEditForm
from accounts.models import UserProfile
from gmail_integration.services import gmail_service

@login_required
def dashboard_view(request):
    current_hour = timezone.localtime(timezone.now()).hour
    if current_hour < 12:
        greeting = "Good Morning"
    elif current_hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    profile = getattr(request.user, 'profile', None)
    display_name = profile.get_display_name() if profile else (request.user.get_full_name() or request.user.username)
    stats = get_dashboard_stats(request.user)
    gmail_status = gmail_service.get_account_status(request.user)

    context = {
        'page_title': 'Dashboard',
        'greeting': greeting,
        'display_name': display_name,
        'stats': stats,
        'gmail_status': gmail_status,
    }
    return render(request, 'dashboard.html', context)


@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'ai_settings':
            groq_key = request.POST.get('groq_api_key', '').strip()
            ai_prov = request.POST.get('ai_provider', 'groq').strip()
            groq_mdl = request.POST.get('groq_model', 'openai/gpt-oss-120b').strip()
            openai_key = request.POST.get('openai_api_key', '').strip()

            updates = {
                'AI_PROVIDER': ai_prov,
                'GROQ_MODEL': groq_mdl,
            }
            if groq_key:
                updates['GROQ_API_KEY'] = groq_key
            if openai_key:
                updates['AI_API_KEY'] = openai_key

            from ai_engine.env_manager import update_env_file
            update_env_file(updates)
            messages.success(request, f"AI configuration saved! Primary provider: {ai_prov.upper()}, Model: {groq_mdl}")
            return redirect('dashboard:settings')

        form = UserProfileEditForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully!")
            return redirect('dashboard:settings')
        else:
            messages.error(request, "Please check the errors in the form.")
    else:
        form = UserProfileEditForm(instance=profile)

    gmail_status = gmail_service.get_account_status(request.user)

    groq_key = getattr(settings, 'GROQ_API_KEY', '')
    groq_configured = bool(groq_key and not str(groq_key).startswith('gsk_your-groq'))
    openai_key = getattr(settings, 'AI_API_KEY', '')
    openai_configured = bool(openai_key and not str(openai_key).startswith('sk-your-openai'))

    context = {
        'page_title': 'Settings',
        'form': form,
        'profile': profile,
        'ai_provider': getattr(settings, 'AI_PROVIDER', 'groq'),
        'ai_model': getattr(settings, 'AI_MODEL', 'gpt-4o-mini'),
        'groq_model': getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-120b'),
        'groq_configured': groq_configured,
        'openai_configured': openai_configured,
        'gmail_status': gmail_status,
        'notification_interval': getattr(settings, 'NOTIFICATION_POLL_INTERVAL', 60),
    }
    return render(request, 'settings.html', context)


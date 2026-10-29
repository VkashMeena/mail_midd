from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from dashboard import views as dashboard_views
from emails import views as email_views
from notifications import views as notification_views
from ai_engine import views as ai_views
from accounts import views as account_views
from gmail_integration import views as gmail_views
from config import views as config_views

handler400 = 'config.views.error_400_view'
handler403 = 'config.views.error_403_view'
handler404 = 'config.views.error_404_view'
handler500 = 'config.views.error_500_view'

urlpatterns = [
    path('health/', config_views.health_check_view, name='health_check'),
    path('admin/', admin.site.urls),

    # Dashboard & Workspace
    path('', dashboard_views.dashboard_view, name='dashboard'),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    path('settings/', dashboard_views.settings_view, name='settings'),
    path('settings/gmail/', gmail_views.gmail_account_view, name='settings_gmail'),
    path('profile/', account_views.profile_view, name='profile'),
    path('settings/password/', account_views.password_change_view, name='password_change'),

    # Authentication
    path('login/', account_views.login_view, name='login'),
    path('register/', account_views.register_view, name='register'),
    path('logout/', account_views.logout_view, name='logout'),
    path('accounts/', include('accounts.urls', namespace='accounts')),

    # Password Reset Flow
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset_form.html',
            email_template_name='auth/password_reset_email.html',
            subject_template_name='auth/password_reset_subject.txt',
            success_url='/password-reset/done/'
        ),
        name='password_reset'
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html'
        ),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html',
            success_url='/reset/done/'
        ),
        name='password_reset_confirm'
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),

    # Emails
    path('inbox/', email_views.inbox_view, name='inbox'),
    path('inbox/<int:email_id>/', email_views.email_detail_view, name='inbox_detail'),
    path('inbox/<int:email_id>/raw/', email_views.email_raw_html_view, name='inbox_raw_html'),
    path('inbox/<int:email_id>/override/', email_views.override_email_ai_view, name='inbox_override_ai'),
    path('inbox/<int:email_id>/action/<str:action>/', email_views.toggle_email_action_view, name='inbox_toggle_action'),
    path('important/', email_views.important_view, name='important'),
    path('pinned/', email_views.pinned_view, name='pinned'),
    path('categories/', email_views.categories_view, name='categories'),
    path('categories/<path:category_name>/', email_views.category_detail_view, name='category_detail'),
    path('category/<path:category_name>/', email_views.category_detail_view, name='category_direct'),
    path('priority-senders/', email_views.priority_senders_view, name='priority_senders'),
    path('important-senders/', email_views.priority_senders_view, name='important_senders'),
    path('emails/', include('emails.urls', namespace='emails')),

    # Gmail Integration
    path('gmail/', include('gmail_integration.urls', namespace='gmail')),

    # Notifications
    path('notifications/', notification_views.notifications_view, name='notifications'),
    path('notifications/', include('notifications.urls', namespace='notifications')),
    path('notifs/', include('notifications.urls', namespace='notifications_app')),
    path('settings/notifications/', notification_views.notification_settings_view, name='settings_notifications'),

    # AI Engine & Phase 7 Daily Summary & Smart Reply
    path('summary/today/', ai_views.ai_summary_view, name='summary_today'),
    path('summary/generate/', ai_views.generate_summary_view, name='summary_generate'),
    path('summary/', ai_views.ai_summary_view, name='summary'),
    path('summary/<str:date_str>/', ai_views.ai_summary_view, name='summary_date'),
    path('ai-summary/', ai_views.ai_summary_view, name='ai_summary'),
    path('ai-reply/', ai_views.ai_reply_view, name='ai_reply'),
    path('emails/<int:email_id>/reply/', ai_views.ai_reply_view, name='email_reply'),
    path('emails/<int:email_id>/reply/generate/', ai_views.generate_reply_action, name='email_reply_generate'),
    path('emails/<int:email_id>/reply/draft/', ai_views.save_reply_draft_action, name='email_reply_draft'),
    path('emails/<int:email_id>/reply/send/', ai_views.send_reply_action, name='email_reply_send'),
    path('emails/<int:email_id>/reply/template/', ai_views.apply_template_action, name='email_reply_template'),
    path('emails/<int:email_id>/analyze/', ai_views.email_analyzer_view, name='email_analyze'),
    path('ai-analyzer/', ai_views.ai_analyzer_hub_view, name='ai_analyzer'),
    path('reply/templates/', ai_views.reply_templates_manage_view, name='reply_templates_manage'),
    path('reply/templates/<int:template_id>/delete/', ai_views.reply_template_delete_view, name='reply_template_delete'),
    path('ai/', include('ai_engine.urls', namespace='ai_engine')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.urls import path
from . import views

app_name = 'ai_engine'

urlpatterns = [
    path('', views.ai_dashboard_view, name='dashboard'),
    path('analyzer/', views.ai_analyzer_hub_view, name='analyzer_hub'),
    path('analyzer/<int:email_id>/', views.email_analyzer_view, name='analyzer_email'),

    path('analyze/<int:email_id>/', views.analyze_single_view, name='analyze_single'),
    path('reanalyze/<int:email_id>/', views.reanalyze_single_view, name='reanalyze_single'),
    path('analyze-batch/', views.analyze_batch_view, name='analyze_batch'),
    path('analyze-unprocessed/', views.analyze_unprocessed_view, name='analyze_unprocessed'),
    path('retry-failed/', views.retry_failed_view, name='retry_failed'),


    # Daily Summary Routes
    path('summary/', views.ai_summary_view, name='summary'),
    path('summary/today/', views.ai_summary_view, name='summary_today'),
    path('summary/generate/', views.generate_summary_view, name='summary_generate'),
    path('summary/<str:date_str>/', views.ai_summary_view, name='summary_date'),

    # Reply Routes
    path('reply/', views.ai_reply_view, name='reply'),
    path('reply/<int:email_id>/', views.ai_reply_view, name='reply_for_email'),
    path('reply/<int:email_id>/generate/', views.generate_reply_action, name='reply_generate'),
    path('reply/<int:email_id>/draft/', views.save_reply_draft_action, name='reply_draft'),
    path('reply/<int:email_id>/send/', views.send_reply_action, name='reply_send'),
    path('reply/<int:email_id>/template/', views.apply_template_action, name='reply_template'),
    path('reply/templates/', views.reply_templates_manage_view, name='reply_templates'),
    path('reply/templates/<int:template_id>/delete/', views.reply_template_delete_view, name='reply_template_delete'),
    path('reply/preview/', views.ai_reply_preview_api, name='reply_preview'),
]

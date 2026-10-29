from django.urls import path
from . import views

app_name = 'emails'

urlpatterns = [
    path('', views.inbox_view, name='inbox'),
    path('<int:email_id>/', views.email_detail_view, name='detail'),
    path('<int:email_id>/raw/', views.email_raw_html_view, name='raw_html'),
    path('<int:email_id>/override/', views.override_email_ai_view, name='override_ai'),
    path('important/', views.important_view, name='important'),
    path('pinned/', views.pinned_view, name='pinned'),
    path('categories/', views.categories_view, name='categories'),
    path('categories/<path:category_name>/', views.category_detail_view, name='category_detail'),
    path('category/<path:category_name>/', views.category_detail_view, name='category_alias'),
    path('priority-senders/', views.priority_senders_view, name='priority_senders'),
    path('important-senders/', views.priority_senders_view, name='important_senders'),
    path('priority-senders/add/', views.add_priority_sender_view, name='priority_sender_add'),
    path('priority-senders/<int:sender_id>/delete/', views.delete_priority_sender_view, name='priority_sender_delete'),
    path('<int:email_id>/action/<str:action>/', views.toggle_email_action_view, name='toggle_action'),
]

from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notifications_view, name='index'),
    path('important/', views.important_notifications_view, name='important'),
    path('<int:notification_id>/read/', views.mark_notification_read_view, name='mark_read'),
    path('read-all/', views.mark_all_notifications_read_view, name='mark_all_read'),
    path('<int:notification_id>/delete/', views.delete_notification_view, name='delete'),
    path('unread-count/', views.unread_count_view, name='unread_count'),
    path('push/subscribe/', views.push_subscribe_view, name='push_subscribe'),
    path('test/', views.test_notification_view, name='test_notification'),
]

from django.urls import path
from . import views

app_name = 'gmail'

urlpatterns = [
    path('connect/', views.connect_view, name='connect'),
    path('oauth/authorize-send/', views.authorize_send_view, name='authorize_send'),
    path('oauth/callback/', views.callback_view, name='callback'),
    path('disconnect/', views.disconnect_view, name='disconnect'),
    path('sync/', views.sync_view, name='sync'),
    path('status/', views.status_api_view, name='status'),
    path('account/', views.gmail_account_view, name='account'),
]

"""
Django settings for ai_smart_mail_manager project.
Phase 2: Authentication + Gmail Integration Foundation.
"""

from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Detect Vercel Serverless Environment
IS_VERCEL = 'VERCEL' in os.environ or os.environ.get('VERCEL') == '1'

# Load environment variables
load_dotenv(BASE_DIR / '.env', override=True)

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-ai-smart-mail-manager-phase1-dev-key-78x9a2b3c4'
)

DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')

allowed_hosts_str = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost')
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_str.split(',') if host.strip()]
if '.vercel.app' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.extend(['.vercel.app', '.now.sh'])
if IS_VERCEL or DEBUG:
    if '*' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('*')

CSRF_TRUSTED_ORIGINS = [
    'https://*.vercel.app',
    'https://*.now.sh',
    'http://127.0.0.1:8000',
    'http://localhost:8000',
]
csrf_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
if csrf_env:
    CSRF_TRUSTED_ORIGINS.extend([origin.strip() for origin in csrf_env.split(',') if origin.strip()])

# Custom User Model (Email as primary identifier)
AUTH_USER_MODEL = 'accounts.User'

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party modules
    'channels',

    # Local application modules
    'accounts.apps.AccountsConfig',
    'emails.apps.EmailsConfig',
    'dashboard.apps.DashboardConfig',
    'notifications.apps.NotificationsConfig',
    'ai_engine.apps.AiEngineConfig',
    'gmail_integration.apps.GmailIntegrationConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.global_ui_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# Supports PostgreSQL in production via DATABASE_URL and SQLite in local/serverless development
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    db_path = (Path('/tmp') / 'db.sqlite3') if IS_VERCEL else (BASE_DIR / 'db.sqlite3')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': db_path,
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Security & Session Configuration
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 1209600  # 2 weeks default

# Production Security Headers & SSL Hardening
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    X_FRAME_OPTIONS = 'DENY'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1')
else:
    X_FRAME_OPTIONS = 'SAMEORIGIN'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = (Path('/tmp') / 'staticfiles') if IS_VERCEL else (BASE_DIR / 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
WHITENOISE_MANIFEST_STRICT = False
WHITENOISE_USE_FINDERS = True

# Media files (Avatars, Uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = (Path('/tmp') / 'media') if IS_VERCEL else (BASE_DIR / 'media')

# Authentication URLs
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:index'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_OAUTH_CLIENT_ID') or ''
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET') or os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET') or ''
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8000/gmail/oauth/callback/')
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get('GOOGLE_OAUTH_REDIRECT_URI', 'http://127.0.0.1:8000/accounts/google/callback/')
GMAIL_SCOPES = os.environ.get(
    'GMAIL_SCOPES',
    'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email'
)
GMAIL_TOKEN_ENCRYPTION_KEY = os.environ.get('GMAIL_TOKEN_ENCRYPTION_KEY', '')
GMAIL_INITIAL_SYNC_LIMIT = int(os.environ.get('GMAIL_INITIAL_SYNC_LIMIT', 100))
GMAIL_SYNC_BATCH_SIZE = int(os.environ.get('GMAIL_SYNC_BATCH_SIZE', 25))

# Email Backend Configuration (For password reset & system alerts)
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@smartmail.ai')

# AI Engine Configuration
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'groq')
AI_API_KEY = os.environ.get('AI_API_KEY', '')
AI_MODEL = os.environ.get('AI_MODEL', 'gpt-4o-mini')
AI_TEMPERATURE = float(os.environ.get('AI_TEMPERATURE', '0.2'))
AI_MAX_TOKENS = int(os.environ.get('AI_MAX_TOKENS', '500'))
AI_CLASSIFICATION_ENABLED = os.environ.get('AI_CLASSIFICATION_ENABLED', 'True').lower() in ('true', '1')
AI_MAX_EMAIL_CHARS = int(os.environ.get('AI_MAX_EMAIL_CHARS', '10000'))
AI_BATCH_SIZE = int(os.environ.get('AI_BATCH_SIZE', '10'))
AI_MAX_RETRIES = int(os.environ.get('AI_MAX_RETRIES', '3'))
AI_TIMEOUT = int(os.environ.get('AI_TIMEOUT', '30'))
AI_BASE_URL = os.environ.get('AI_BASE_URL', '')

# Groq API Configuration (Fast LPU Inference)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-120b')
GROQ_BASE_URL = os.environ.get('GROQ_BASE_URL', 'https://api.groq.com/openai/v1')

# Phase 7 & Upgrade: AI Reply Assistant Configuration
AI_REPLY_ENABLED = os.environ.get('AI_REPLY_ENABLED', 'True').lower() in ('true', '1')
AI_REPLY_PROVIDER = os.environ.get('AI_REPLY_PROVIDER', AI_PROVIDER)
AI_REPLY_MODEL = os.environ.get('AI_REPLY_MODEL', AI_MODEL)
AI_REPLY_MAX_EMAIL_CHARS = int(os.environ.get('AI_REPLY_MAX_EMAIL_CHARS', '30000'))
AI_REPLY_MAX_OUTPUT_TOKENS = int(os.environ.get('AI_REPLY_MAX_OUTPUT_TOKENS', os.environ.get('AI_REPLY_MAX_TOKENS', '1500')))
AI_REPLY_MAX_TOKENS = AI_REPLY_MAX_OUTPUT_TOKENS
AI_REPLY_TIMEOUT = int(os.environ.get('AI_REPLY_TIMEOUT', os.environ.get('AI_TIMEOUT', '45')))
AI_SUMMARY_MAX_EMAILS = int(os.environ.get('AI_SUMMARY_MAX_EMAILS', '100'))
AI_SUMMARY_MAX_TOKENS = int(os.environ.get('AI_SUMMARY_MAX_TOKENS', '1200'))

# Channels & Real-time Layer Configuration
CHANNELS_REDIS_URL = os.environ.get('CHANNELS_REDIS_URL', '').strip()
if CHANNELS_REDIS_URL and CHANNELS_REDIS_URL.startswith(('redis://', 'rediss://', 'unix://')):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [CHANNELS_REDIS_URL],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Phase 6 Notification & Push Configuration
WEBSOCKET_ENABLED = os.environ.get('WEBSOCKET_ENABLED', 'True').lower() in ('true', '1')
WEB_PUSH_ENABLED = os.environ.get('WEB_PUSH_ENABLED', 'False').lower() in ('true', '1')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_CLAIMS_EMAIL = os.environ.get('VAPID_CLAIMS_EMAIL', 'admin@smartmail.ai')
GMAIL_SYNC_INTERVAL_SECONDS = int(os.environ.get('GMAIL_SYNC_INTERVAL_SECONDS', '300'))
NOTIFICATION_RETENTION_DAYS = int(os.environ.get('NOTIFICATION_RETENTION_DAYS', '90'))
NOTIFICATION_POLL_INTERVAL = int(os.environ.get('NOTIFICATION_POLL_INTERVAL', '30'))

# ==============================================================================
# Phase 8: Celery Asynchronous Task Queue Configuration
# ==============================================================================
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit

# ==============================================================================
# Phase 8: Production Structured Logging & Credential Scrubbing
# ==============================================================================
if IS_VERCEL:
    LOGS_DIR = Path('/tmp') / 'logs'
else:
    LOGS_DIR = BASE_DIR / 'logs'

try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

logging_handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
        'filters': ['sensitive_data_filter'],
    },
}

if not IS_VERCEL:
    logging_handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOGS_DIR / 'smartmail.log',
        'maxBytes': 10 * 1024 * 1024,  # 10 MB per file
        'backupCount': 5,
        'formatter': 'verbose',
        'filters': ['sensitive_data_filter'],
        'encoding': 'utf-8',
    }

active_handlers = ['console'] if IS_VERCEL else ['console', 'file']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'sensitive_data_filter': {
            '()': 'config.logging_filters.SensitiveDataFilter',
        },
    },
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': logging_handlers,
    'root': {
        'handlers': active_handlers,
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': active_handlers,
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'emails': {
            'handlers': active_handlers,
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'ai_engine': {
            'handlers': active_handlers,
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'gmail_integration': {
            'handlers': active_handlers,
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'notifications': {
            'handlers': active_handlers,
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}


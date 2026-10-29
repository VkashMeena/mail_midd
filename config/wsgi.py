"""
WSGI config for ai_smart_mail_manager project.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
app = application

# Run migrations once per serverless container cold start if running on Vercel without external DB
if os.environ.get('VERCEL') and not os.environ.get('DATABASE_URL'):
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False)
    except Exception as exc:
        print(f"Vercel auto-migration status: {exc}")

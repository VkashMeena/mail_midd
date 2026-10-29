"""
Vercel serverless entry point for Django.
"""
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

# Auto-migrate SQLite on Vercel ephemeral /tmp if not using external DATABASE_URL
if os.environ.get('VERCEL') and not os.environ.get('DATABASE_URL'):
    try:
        from django.db import connection
        tables = connection.introspection.table_names()
        if 'accounts_user' not in tables:
            from django.core.management import call_command
            call_command('migrate', verbosity=0, interactive=False)
    except Exception as db_exc:
        print(f"Serverless auto-migration note: {db_exc}")

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()
application = app

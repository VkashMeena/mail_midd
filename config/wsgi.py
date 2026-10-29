"""
WSGI config for ai_smart_mail_manager project.
"""
import os
import sys
import shutil
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Fast cold-start SQLite initialization for Vercel (/tmp)
if os.environ.get('VERCEL') and not os.environ.get('DATABASE_URL'):
    try:
        db_dest = Path('/tmp') / 'db.sqlite3'
        if not db_dest.exists() or db_dest.stat().st_size == 0:
            template_db = PROJECT_ROOT / 'initial_db.sqlite3'
            if template_db.exists():
                shutil.copyfile(template_db, db_dest)
    except Exception as exc:
        print(f"SQLite bootstrap notice: {exc}")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application

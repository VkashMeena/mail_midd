"""
WSGI config for ai_smart_mail_manager project.
"""
import os
import sys
import shutil
import traceback
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

_django_app = None
_init_error = None

try:
    from django.core.wsgi import get_wsgi_application
    _django_app = get_wsgi_application()
except Exception:
    _init_error = traceback.format_exc()
    print(f"Django WSGI startup error:\n{_init_error}")


def app(environ, start_response):
    if _init_error is not None:
        error_page = (
            f"=== DJANGO STARTUP ERROR ===\n\n"
            f"{_init_error}\n\n"
            f"Python Version: {sys.version}\n"
            f"sys.path: {sys.path}\n"
        ).encode('utf-8')
        start_response("200 OK", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(error_page))),
        ])
        return [error_page]

    try:
        return _django_app(environ, start_response)
    except Exception:
        req_error = (
            f"=== DJANGO RUNTIME REQUEST ERROR ===\n\n"
            f"{traceback.format_exc()}\n\n"
            f"PATH_INFO: {environ.get('PATH_INFO')}\n"
        ).encode('utf-8')
        start_response("200 OK", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(req_error))),
        ])
        return [req_error]


application = app

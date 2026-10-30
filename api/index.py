"""
Vercel serverless entry point for Django with fail-safe diagnostics.
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

_django_app = None
_init_error = None


def get_django_app():
    global _django_app, _init_error
    if _django_app is not None:
        return _django_app
    if _init_error is not None:
        return None

    try:
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
        _django_app = get_wsgi_application()
        return _django_app
    except Exception:
        _init_error = traceback.format_exc()
        print(f"Django WSGI initialization failed:\n{_init_error}")
        return None


def app(environ, start_response):
    raw_path = environ.get('PATH_INFO', '')
    query_str = environ.get('QUERY_STRING', '')

    # Diagnostic ping endpoint
    if raw_path == '/vercel-diag' or 'diag=1' in query_str:
        try:
            root_files = [p.name for p in PROJECT_ROOT.iterdir()] if PROJECT_ROOT.exists() else []
        except Exception as e:
            root_files = [f"Error listing: {e}"]
        env_sample = {k: str(v) for k, v in environ.items() if not k.startswith('HTTP_COOKIE')}
        diag_info = (
            f"=== VERCEL PYTHON ENVIRONMENT DIAGNOSTICS ===\n\n"
            f"Python Version: {sys.version}\n"
            f"PROJECT_ROOT: {PROJECT_ROOT} (exists: {PROJECT_ROOT.exists()})\n"
            f"sys.path: {sys.path}\n\n"
            f"PROJECT_ROOT contents: {root_files}\n\n"
            f"WSGI Environ:\n" + "\n".join(f"  {k} = {v}" for k, v in sorted(env_sample.items())) + "\n"
        ).encode('utf-8')
        start_response("200 OK", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(diag_info))),
        ])
        return [diag_info]

    # Handle Vercel rewrite PATH_INFO:
    if raw_path in ('/api/index', '/api/index.py', '/api', '/api/'):
        matched_path = environ.get('HTTP_X_MATCHED_PATH') or environ.get('HTTP_X_FORWARDED_URI')
        if matched_path and not matched_path.startswith('/api/index'):
            environ['PATH_INFO'] = matched_path.split('?')[0]
        else:
            environ['PATH_INFO'] = '/'

    django_handler = get_django_app()

    if django_handler is None:
        error_msg = (
            f"=== VERCEL DJANGO INITIALIZATION ERROR ===\n\n"
            f"{_init_error}\n\n"
            f"Python Version: {sys.version}\n"
            f"sys.path: {sys.path}\n"
        ).encode('utf-8')
        start_response("200 OK", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(error_msg))),
        ])
        return [error_msg]

    try:
        return django_handler(environ, start_response)
    except Exception:
        req_error = (
            f"=== VERCEL DJANGO RUNTIME REQUEST ERROR ===\n\n"
            f"{traceback.format_exc()}\n\n"
            f"PATH_INFO: {environ.get('PATH_INFO')}\n"
        ).encode('utf-8')
        start_response("200 OK", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(req_error))),
        ])
        return [req_error]


application = app

"""
Vercel serverless entry point for Django with built-in runtime diagnostics.
"""
import os
import sys
import traceback
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_app = None
startup_error = None

try:
    from django.core.wsgi import get_wsgi_application
    django_app = get_wsgi_application()

    # Automatically create SQLite tables if running in serverless /tmp
    if os.environ.get('VERCEL') and not os.environ.get('DATABASE_URL'):
        try:
            db_path = Path('/tmp') / 'db.sqlite3'
            if not db_path.exists() or db_path.stat().st_size == 0:
                from django.core.management import call_command
                call_command('migrate', verbosity=0, interactive=False)
        except Exception as db_exc:
            print(f"Serverless SQLite migration note: {db_exc}")

except Exception:
    startup_error = traceback.format_exc()
    print("Django Startup Failure:\n", startup_error)


def app(environ, start_response):
    global django_app, startup_error

    if startup_error:
        status = '200 OK'
        headers = [('Content-Type', 'text/html; charset=utf-8')]
        start_response(status, headers)
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>AI Smart Mail Manager - Startup Diagnostic</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 30px; background: #0f172a; color: #f8fafc;">
    <div style="max-width: 850px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border: 1px solid #334155;">
        <h1 style="font-size: 20px; color: #f87171; margin-top: 0;">Django Startup Diagnostic</h1>
        <p style="color: #cbd5e1; font-size: 14px;">An exception occurred while starting Django on Vercel:</p>
        <pre style="background: #0f172a; color: #fca5a5; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.5; border: 1px solid #475569;">{startup_error}</pre>
    </div>
</body>
</html>"""
        return [html.encode('utf-8')]

    try:
        return django_app(environ, start_response)
    except Exception:
        req_error = traceback.format_exc()
        print("Django Request Failure:\n", req_error)
        status = '200 OK'
        headers = [('Content-Type', 'text/html; charset=utf-8')]
        start_response(status, headers)
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>AI Smart Mail Manager - Request Diagnostic</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 30px; background: #0f172a; color: #f8fafc;">
    <div style="max-width: 850px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); border: 1px solid #334155;">
        <h1 style="font-size: 20px; color: #f87171; margin-top: 0;">Django Request Diagnostic</h1>
        <p style="color: #cbd5e1; font-size: 14px;">An exception occurred while processing this request:</p>
        <pre style="background: #0f172a; color: #fca5a5; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.5; border: 1px solid #475569;">{req_error}</pre>
    </div>
</body>
</html>"""
        return [html.encode('utf-8')]


# Export application and handler for Vercel WSGI / ASGI compatibility
application = app
handler = app

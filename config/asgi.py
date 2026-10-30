"""
ASGI config for ai_smart_mail_manager project.
Exposes the ASGI callable as a module-level variable named ``application``.
Supports HTTP and real-time WebSockets via Django Channels.
"""

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import notifications.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(
            notifications.routing.websocket_urlpatterns
        )
    ),
})

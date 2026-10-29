"""
Django configuration package initialization.
Exposes Celery application for asynchronous background worker tasks.
"""
try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except Exception:
    celery_app = None
    __all__ = ()

"""
Django configuration package initialization.
Exposes Celery application for asynchronous background worker tasks.
"""
from .celery import app as celery_app

__all__ = ('celery_app',)

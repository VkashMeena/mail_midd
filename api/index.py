"""
Vercel serverless entry point alias for Django.
"""
import os
from config.wsgi import app

# Export application for Vercel
application = app

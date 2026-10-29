#!/bin/bash
# Install dependencies
python3 -m pip install -r requirements.txt

# Run migrations and collect static files
python3 manage.py collectstatic --noinput --clear

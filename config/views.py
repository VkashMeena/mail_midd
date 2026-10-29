"""
System-level views for health monitoring and custom HTTP error rendering.
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.db import connection


def health_check_view(request):
    """
    Production health check endpoint verifying database connectivity and service readiness.
    Returns HTTP 200 when healthy, or HTTP 503 if primary storage is unreachable.
    """
    health_status = {
        'service': 'AI Smart Mail Manager',
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'database': 'unknown',
        'version': '1.0.0'
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
        health_status['database'] = 'healthy'
        return JsonResponse(health_status, status=200)
    except Exception as exc:
        health_status['status'] = 'unhealthy'
        health_status['database'] = f'unhealthy: {str(exc)}'
        return JsonResponse(health_status, status=503)


def error_400_view(request, exception=None):
    """Custom 400 Bad Request handler."""
    return render(request, '400.html', status=400)


def error_403_view(request, exception=None):
    """Custom 403 Forbidden handler."""
    return render(request, '403.html', status=403)


def error_404_view(request, exception=None):
    """Custom 404 Not Found handler."""
    return render(request, '404.html', status=404)


def error_429_view(request, exception=None):
    """Custom 429 Rate Limited handler."""
    return render(request, '429.html', status=429)


def error_500_view(request):
    """Custom 500 Internal Server Error handler."""
    return render(request, '500.html', status=500)

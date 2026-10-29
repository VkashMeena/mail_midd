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
    """Custom 500 Internal Server Error handler with diagnostic details."""
    import sys, traceback
    from django.http import HttpResponse

    exc_type, exc_value, exc_traceback = sys.exc_info()
    if exc_type is not None:
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        error_details = "".join(tb_lines)
    else:
        error_details = "No traceback captured in sys.exc_info(). Check Vercel Function runtime logs."

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>500 Internal Server Error</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; background: #0f172a; color: #f8fafc;">
    <div style="max-width: 900px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 24px; border: 1px solid #ef4444; box-shadow: 0 4px 20px rgba(0,0,0,0.5);">
        <h1 style="color: #f87171; font-size: 22px; margin-top: 0;">Server Error (500)</h1>
        <p style="color: #cbd5e1; font-size: 14px;">Django encountered the following error while processing the request:</p>
        <pre style="background: #020617; color: #fca5a5; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.5; border: 1px solid #334155;">{error_details}</pre>
    </div>
</body>
</html>"""
    return HttpResponse(html, status=500, content_type="text/html")

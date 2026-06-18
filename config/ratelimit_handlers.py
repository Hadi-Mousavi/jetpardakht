"""
HTTP 429 handler for django-ratelimit.

Wired via settings.RATELIMIT_VIEW and RatelimitMiddleware.
"""

from django.http import JsonResponse
from django.shortcuts import render

RATE_LIMIT_MESSAGE = (
    'تعداد درخواست‌های شما بیش از حد مجاز است. '
    'لطفاً کمی صبر کنید و دوباره تلاش کنید.'
)


def ratelimited_error(request, exception):
    """Return HTTP 429 with a friendly Persian message."""
    accept = request.headers.get('Accept', '')
    if (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in accept
        or request.path.startswith('/dashboard/orders/ajax/')
        or request.path.startswith('/auth/otp/')
    ):
        return JsonResponse({'error': RATE_LIMIT_MESSAGE}, status=429)

    return render(
        request,
        'ratelimit/429.html',
        {'message': RATE_LIMIT_MESSAGE},
        status=429,
    )

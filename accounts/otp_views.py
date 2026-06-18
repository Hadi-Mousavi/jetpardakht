"""
OTP request/resend endpoints (Phase 1 stubs).

Rate limits are enforced now; business logic will be added in a later phase.
See docs/PRODUCT_SPEC.md — POST /auth/otp/request, POST /auth/otp/resend.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

_OTP_NOT_ACTIVE = (
    'سرویس احراز هویت با کد یکبار مصرف هنوز فعال نشده است. '
    'لطفاً از ورود با ایمیل استفاده کنید.'
)


@require_POST
@ratelimit(key='ip', rate='3/10m', method='POST', block=True, group='otp_generate')
def otp_request(request):
    """Generate and send an OTP code (stub — not yet implemented)."""
    return JsonResponse({'error': _OTP_NOT_ACTIVE}, status=501)


@require_POST
@ratelimit(key='ip', rate='3/10m', method='POST', block=True, group='otp_resend')
def otp_resend(request):
    """Resend a previously issued OTP code (stub — not yet implemented)."""
    return JsonResponse({'error': _OTP_NOT_ACTIVE}, status=501)

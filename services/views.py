"""
Customer-facing views for the service catalog and dynamic order submission.

URL map (registered in services/urls.py):
    /dashboard/services/                        → service_catalog
    /dashboard/services/<slug>/                 → service_order   (GET + POST)
    /dashboard/services/files/<pk>/download/    → field_value_download
"""

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.db import models as django_models, transaction
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django_ratelimit.decorators import ratelimit

from orders.models import Category, Order, SubCategory

from .forms import build_order_form
from .models import OrderFieldValue, Service, ServiceCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_service_slots(service):
    """
    Return (Category, SubCategory) suitable for an Order created from a Service.

    A single "خدمات آنلاین" Category is shared by all service orders.
    One SubCategory per Service is created on demand (matched by stable slug).
    """
    cat, _ = Category.objects.get_or_create(
        slug='online-services',
        defaults={'title': 'خدمات آنلاین', 'is_active': True, 'display_order': 999},
    )
    sub, _ = SubCategory.objects.get_or_create(
        category=cat,
        title=service.name[:200],
        defaults={'is_active': True},
    )
    return cat, sub


def _save_field_values(order, service, cleaned_data):
    """Persist OrderFieldValue records for every dynamic form field."""
    for sf in service.fields.order_by('sort_order', 'id'):
        value = cleaned_data.get(sf.field_name)
        if value is None:
            continue
        if sf.field_type == 'file':
            OrderFieldValue.objects.create(
                order=order,
                service_field=sf,
                value_file=value,
            )
        else:
            OrderFieldValue.objects.create(
                order=order,
                service_field=sf,
                value_text=str(value),
            )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def service_catalog(request):
    """
    /dashboard/services/

    Display only active ServiceCategories that contain at least one active
    Service, with their services prefetched.
    """
    categories = (
        ServiceCategory.objects
        .filter(is_active=True)
        .prefetch_related(
            django_models.Prefetch(
                'services',
                queryset=Service.objects.filter(is_active=True),
            )
        )
    )
    # Filter out empty categories (uses prefetched data — no extra queries)
    categories = [c for c in categories if c.services.all()]

    return render(request, 'services/catalog.html', {
        'categories': categories,
    })


@ratelimit(key='user', rate='20/h', method='POST', block=True, group='service_orders')
@login_required
def service_order(request, slug):
    """
    /dashboard/services/<slug>/

    GET  → render the dynamically generated order form.
    POST → validate, create Order + OrderFieldValue records, redirect.
    """
    service = get_object_or_404(Service, slug=slug, is_active=True)

    # KYC gate: only if the service requires it
    if service.requires_kyc:
        try:
            kyc_profile = request.user.kyc_profile
            from kyc.models import KYCProfile
            if kyc_profile.status != KYCProfile.STATUS_APPROVED:
                flash.warning(
                    request,
                    'برای استفاده از این سرویس، ابتدا باید احراز هویت شما تأیید شود.',
                )
                return redirect('kyc_submit')
        except Exception:
            flash.warning(
                request,
                'لطفاً ابتدا احراز هویت خود را تکمیل کنید.',
            )
            return redirect('kyc_submit')

    if request.method == 'POST':
        form = build_order_form(service, data=request.POST, files=request.FILES)
        if form.is_valid():
            with transaction.atomic():
                cat, sub = _get_or_create_service_slots(service)
                order = Order.objects.create(
                    user=request.user,
                    category=cat,
                    subcategory=sub,
                    description=service.short_description or service.name,
                    amount=service.base_price,
                    currency=service.currency or '',
                    service=service,
                )
                _save_field_values(order, service, form.cleaned_data)

            flash.success(
                request,
                f'سفارش {order.order_number} با موفقیت ثبت شد.',
            )
            return redirect('order_detail', pk=order.pk)
    else:
        form = build_order_form(service)

    return render(request, 'services/service_order.html', {
        'service': service,
        'form': form,
    })


@login_required
def field_value_download(request, pk):
    """
    /dashboard/services/files/<pk>/download/

    Securely serve an OrderFieldValue file.

    Security:
      - @login_required  — anonymous users cannot access this view.
      - Ownership check  — the file's order must belong to request.user
                           (staff/admin bypass).
      - FileResponse(as_attachment=True) — browser downloads, does not render.
      - File is stored in PRIVATE_MEDIA_ROOT — never accessible without this view.
    """
    fv = get_object_or_404(
        OrderFieldValue.objects.select_related('order', 'service_field'),
        pk=pk,
    )

    # Ownership / permission gate
    if fv.order.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden('دسترسی به این فایل مجاز نیست.')

    if not fv.value_file or not fv.value_file.name:
        raise Http404('فایلی برای این فیلد وجود ندارد.')

    try:
        return FileResponse(
            fv.value_file.open('rb'),
            as_attachment=True,
            filename=fv.value_file.name.split('/')[-1],
        )
    except FileNotFoundError:
        raise Http404('فایل یافت نشد.')

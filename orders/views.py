from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from kyc.models import KYCProfile

from .forms import AttachmentForm, MessageForm, OrderCreateForm
from .models import (
    Order, OrderAttachment, OrderMessage,
    OrderMessageAttachment, SubCategory,
)
from .timeline_display import prepare_timeline_for_display
from .unread import mark_order_admin_messages_read, orders_with_unread_counts
from .utils import validate_upload


# ── helpers ──────────────────────────────────────────────────────────────────

def _kyc_profile(user):
    try:
        return user.kyc_profile
    except KYCProfile.DoesNotExist:
        return None


_STATUS_TIMELINE = {
    Order.STATUS_UNDER_REVIEW: (
        'سفارش در حال بررسی قرار گرفت', 'bi-search', '🔍', 'yellow',
    ),
    Order.STATUS_WAITING_PAYMENT: (
        'سفارش در انتظار پرداخت قرار گرفت', 'bi-credit-card', '💳', 'yellow',
    ),
    Order.STATUS_PAYMENT_REJECTED: (
        'پرداخت رد شد', 'bi-credit-card-fill', '❌', 'red',
    ),
    Order.STATUS_IN_PROGRESS: (
        'سفارش در حال انجام قرار گرفت', 'bi-rocket-takeoff-fill', '🚀', 'orange',
    ),
    Order.STATUS_WAITING_CUSTOMER: (
        'سفارش منتظر اقدام شما است', 'bi-person-exclamation', '⚠️', 'yellow',
    ),
    Order.STATUS_COMPLETED: (
        'سفارش تکمیل شد', 'bi-check-circle-fill', '✅', 'green',
    ),
    Order.STATUS_REJECTED: (
        'سفارش رد شد', 'bi-x-circle-fill', '❌', 'red',
    ),
    Order.STATUS_CANCELLED: (
        'سفارش لغو شد', 'bi-slash-circle', '🚫', 'red',
    ),
}

# Maps status → (title, icon, emoji, color) for status history events
_HISTORY_STATUS_MAP = {
    k: v for k, v in _STATUS_TIMELINE.items()
}

# Recovery/reopen transitions get their own title/icon (keyed by (old, new) pair)
_REOPEN_EVENT_MAP = {
    ('completed', 'in_progress'): (
        'سفارش بازگشایی شد و به مرحله در حال انجام بازگشت',
        'bi-arrow-counterclockwise', '🔄', 'orange',
    ),
    ('cancelled', 'under_review'): (
        'سفارش لغوشده مجدداً به مرحله بررسی بازگشت',
        'bi-arrow-counterclockwise', '🔄', 'yellow',
    ),
}


def _build_order_timeline(order):
    """
    Build a chronological activity feed from existing order-related data.
    No audit/history model — events are inferred from timestamps on related rows.
    """
    events = []

    events.append({
        'title': 'سفارش ثبت شد',
        'emoji': '📦',
        'icon': 'bi-box-seam-fill',
        'timestamp': order.created_at,
        'sort_order': 10,
    })

    # Use status history records if available (workflow engine).
    # Fall back to the current-status single event for older orders.
    from .models import OrderStatusHistory as _History
    history_qs = list(order.status_history.select_related('changed_by').all())
    if history_qs:
        for h in history_qs:
            # Recovery/reopen events take priority over generic status mapping
            reopen_meta = _REOPEN_EVENT_MAP.get((h.old_status, h.new_status))
            if reopen_meta:
                h_title, h_icon, h_emoji, h_color = reopen_meta
            else:
                meta = _HISTORY_STATUS_MAP.get(h.new_status)
                if meta:
                    h_title, h_icon, h_emoji, h_color = meta
                else:
                    h_title = f'وضعیت به «{h.new_status_label}» تغییر کرد'
                    h_icon  = 'bi-arrow-repeat'
                    h_emoji = '🔄'
                    h_color = 'blue'
            events.append({
                'title':      h_title,
                'emoji':      h_emoji,
                'icon':       h_icon,
                'timestamp':  h.created_at,
                'sort_order': 20,
                'color_hint': h_color,
                'note':       h.note,
            })
    elif order.status in _STATUS_TIMELINE:
        title, icon, emoji, color = _STATUS_TIMELINE[order.status]
        events.append({
            'title':      title,
            'emoji':      emoji,
            'icon':       icon,
            'timestamp':  order.updated_at,
            'sort_order': 20,
            'color_hint': color,
        })

    if order.assigned_admin_id:
        events.append({
            'title': 'مسئول سفارش تعیین شد',
            'emoji': '👨‍💼',
            'icon': 'bi-person-badge-fill',
            'timestamp': order.updated_at,
            'sort_order': 30,
        })

    if (
        order.updated_at > order.created_at
        and order.status == Order.STATUS_SUBMITTED
    ):
        events.append({
            'title': 'اطلاعات سفارش ویرایش شد',
            'emoji': '📝',
            'icon': 'bi-pencil-square',
            'timestamp': order.updated_at,
            'sort_order': 40,
        })

    for msg in order.messages.all():
        events.append({
            'title': 'پیام جدید ثبت شد',
            'emoji': '💬',
            'icon': 'bi-chat-dots-fill',
            'timestamp': msg.created_at,
            'sort_order': 50,
        })
        for att in msg.attachments.all():
            events.append({
                'title': 'فایل جدید بارگذاری شد',
                'emoji': '📎',
                'icon': 'bi-paperclip',
                'timestamp': att.uploaded_at,
                'sort_order': 55,
            })

    for att in order.attachments.all():
        events.append({
            'title': 'فایل جدید بارگذاری شد',
            'emoji': '📎',
            'icon': 'bi-paperclip',
            'timestamp': att.created_at,
            'sort_order': 60,
        })

    # Payment events — imported lazily to avoid circular dependency
    from payments.models import Payment as _Payment
    for payment in order.payments.all():
        events.append({
            'title': 'رسید پرداخت ارسال شد',
            'emoji': '💳',
            'icon': 'bi-credit-card-2-front-fill',
            'timestamp': payment.submitted_at,
            'sort_order': 45,
        })
        if payment.status == _Payment.STATUS_APPROVED:
            events.append({
                'title': 'پرداخت تأیید شد',
                'emoji': '💰',
                'icon': 'bi-check-circle-fill',
                'timestamp': payment.reviewed_at or payment.submitted_at,
                'sort_order': 46,
            })
        elif payment.status == _Payment.STATUS_REJECTED:
            events.append({
                'title': 'پرداخت رد شد',
                'emoji': '❌',
                'icon': 'bi-x-circle-fill',
                'timestamp': payment.reviewed_at or payment.submitted_at,
                'sort_order': 47,
            })

    events.sort(
        key=lambda item: (
            item['timestamp'] or timezone.now(),
            item['sort_order'],
        ),
        reverse=True,
    )
    return events


def _render_order_detail(request, order, msg_form=None, attach_form=None):
    """Shared render helper — keeps queryset logic in one place."""
    from payments.forms import PaymentSubmitForm
    from payments.models import Payment

    order_msgs = list(
        order.messages.select_related('sender').prefetch_related('attachments')
    )
    if not request.user.is_staff:
        mark_order_admin_messages_read(order)
    attachments = order.attachments.select_related('uploaded_by')
    timeline    = prepare_timeline_for_display(_build_order_timeline(order))

    # Payment context — only relevant for waiting_payment orders
    payments       = list(order.payments.select_related('reviewed_by').order_by('-submitted_at'))
    latest_payment = payments[0] if payments else None
    has_pending_payment = any(p.status == Payment.STATUS_SUBMITTED for p in payments)
    payment_form   = PaymentSubmitForm()

    # Status history — latest entry first, for showing the most recent note
    status_history = list(order.status_history.select_related('changed_by').all())
    latest_history  = status_history[0] if status_history else None
    action_required = order.status == Order.STATUS_WAITING_CUSTOMER

    # Dynamic service field values (only present for service-catalog orders)
    if order.service_id:
        from services.models import OrderFieldValue
        field_values = list(
            order.field_values
            .select_related('service_field')
            .order_by('service_field__sort_order', 'service_field__id')
        )
    else:
        field_values = []

    return render(request, 'orders/order_detail.html', {
        'order':              order,
        'order_msgs':         order_msgs,
        'attachments':        attachments,
        'timeline_groups':    timeline,
        'msg_form':           msg_form if msg_form is not None else MessageForm(),
        'attach_form':        attach_form if attach_form is not None else AttachmentForm(),
        # payment
        'payments':           payments,
        'latest_payment':     latest_payment,
        'has_pending_payment': has_pending_payment,
        'payment_form':       payment_form,
        # workflow
        'status_history':     status_history,
        'latest_history':     latest_history,
        'action_required':    action_required,
        # service catalog
        'field_values':       field_values,
    })


# ── customer views ────────────────────────────────────────────────────────────

@login_required
def order_list(request):
    orders = (
        orders_with_unread_counts(request.user)
        .select_related('category', 'subcategory')
    )
    kyc         = _kyc_profile(request.user)
    kyc_approved = kyc and kyc.status == KYCProfile.STATUS_APPROVED

    return render(request, 'orders/order_list.html', {
        'orders':       orders,
        'kyc_profile':  kyc,
        'kyc_approved': kyc_approved,
    })


@ratelimit(key='user', rate='20/h', method='POST', block=True, group='file_uploads')
@ratelimit(key='user', rate='10/h', method='POST', block=True, group='order_create')
@login_required
def order_create(request):
    kyc          = _kyc_profile(request.user)
    kyc_approved = kyc and kyc.status == KYCProfile.STATUS_APPROVED

    if not kyc_approved:
        return render(request, 'orders/order_create.html', {
            'kyc_blocked': True,
            'kyc_profile': kyc,
        })

    if request.method == 'POST':
        form = OrderCreateForm(request.POST)
        if form.is_valid():
            # Validate every attachment file before committing the order row.
            files  = request.FILES.getlist('attachment_files')
            titles = request.POST.getlist('attachment_titles')
            file_errors = []
            for f in files:
                try:
                    validate_upload(f)
                except ValidationError as e:
                    file_errors.append(f'{f.name}: {e.message}')

            if file_errors:
                for err in file_errors:
                    flash.error(request, err)
            else:
                order      = form.save(commit=False)
                order.user = request.user
                order.save()

                for idx, f in enumerate(files):
                    title = titles[idx] if idx < len(titles) else ''
                    OrderAttachment.objects.create(
                        order=order, file=f,
                        title=title, uploaded_by=request.user,
                    )

                flash.success(
                    request,
                    f'سفارش شما با شماره {order.order_number} با موفقیت ثبت شد.',
                )
                return redirect('order_detail', pk=order.pk)
    else:
        form = OrderCreateForm()

    return render(request, 'orders/order_create.html', {
        'form':        form,
        'kyc_blocked': False,
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return _render_order_detail(request, order)


@ratelimit(key='user', rate='20/h', method='POST', block=True, group='file_uploads')
@ratelimit(key='user', rate='20/h', method='POST', block=True, group='order_messages')
@login_required
def order_send_message(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)

    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            msg_files = request.FILES.getlist('message_files')

            # Validate attachments before saving anything.
            file_errors = []
            for f in msg_files:
                try:
                    validate_upload(f)
                except ValidationError as e:
                    file_errors.append(f'{f.name}: {e.message}')

            if file_errors:
                for err in file_errors:
                    flash.error(request, err)
                return _render_order_detail(request, order, msg_form=form)
            else:
                msg        = form.save(commit=False)
                msg.order  = order
                msg.sender = request.user
                msg.save()
                for f in msg_files:
                    OrderMessageAttachment.objects.create(message=msg, file=f)
                return redirect('order_detail', pk=pk)
        else:
            for err in form.errors.get('message', []):
                flash.error(request, err)
            return _render_order_detail(request, order, msg_form=form)

    return redirect('order_detail', pk=pk)


@ratelimit(key='user', rate='20/h', method='POST', block=True, group='file_uploads')
@login_required
def order_upload_attachment(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)

    if request.method == 'POST':
        form = AttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            att             = form.save(commit=False)
            att.order       = order
            att.uploaded_by = request.user
            att.save()
            return redirect('order_detail', pk=pk)
        for err in form.errors.get('file', []):
            uploaded = request.FILES.get('file')
            name = uploaded.name if uploaded else ''
            flash.error(request, f'{name}: {err}' if name else err)
        return _render_order_detail(request, order, attach_form=form)

    return redirect('order_detail', pk=pk)


# ── AJAX ──────────────────────────────────────────────────────────────────────

@login_required
def ajax_subcategories(request):
    """Return JSON list of active subcategories for a given category."""
    try:
        cat_id = int(request.GET.get('category_id', ''))
    except (ValueError, TypeError):
        return JsonResponse({'subcategories': []})

    subs = (
        SubCategory.objects
        .filter(category_id=cat_id, is_active=True)
        .order_by('display_order', 'title')
        .values('id', 'title')
    )
    return JsonResponse({'subcategories': list(subs)})


# ── public tracking page (kept for backward compatibility) ────────────────────

@ratelimit(key='ip', rate='30/m', block=True, group='order_tracking')
def order_tracking(request):
    order = None
    error = None
    query = request.GET.get('code', '').strip().upper()

    if query:
        try:
            order = Order.objects.select_related(
                'category', 'subcategory',
            ).get(order_number=query)
        except Order.DoesNotExist:
            error = 'شماره سفارش یافت نشد. لطفاً دوباره بررسی کنید.'

    return render(request, 'orders/order_tracking.html', {
        'order': order,
        'error': error,
        'query': query,
    })


# ── legacy stubs (old URLs still wired in config/urls.py) ─────────────────────

def order_success(request, tracking_code=None):
    return redirect('order_list')


# ── secure file download views ────────────────────────────────────────────────

@login_required
def order_attachment_download(request, pk):
    """
    Serve an OrderAttachment file.
    Access rules:
      - Staff: unrestricted.
      - Customer: must own the order the attachment belongs to.
    Returns 404 if the attachment does not exist, is not owned by the
    customer, or the file on disk is missing.
    """
    if request.user.is_staff:
        att = get_object_or_404(OrderAttachment, pk=pk)
    else:
        att = get_object_or_404(
            OrderAttachment.objects.select_related('order'),
            pk=pk,
            order__user=request.user,
        )

    if not att.file:
        raise Http404

    try:
        return FileResponse(
            att.file.open('rb'),
            as_attachment=True,
            filename=att.filename,
        )
    except (FileNotFoundError, OSError):
        raise Http404


@login_required
def message_attachment_download(request, pk):
    """
    Serve an OrderMessageAttachment file.
    Access rules:
      - Staff: unrestricted.
      - Customer: must own the order the message belongs to.
    Returns 404 if the attachment does not exist, is not owned by the
    customer, or the file on disk is missing.
    """
    if request.user.is_staff:
        att = get_object_or_404(
            OrderMessageAttachment.objects.select_related('message__order'),
            pk=pk,
        )
    else:
        att = get_object_or_404(
            OrderMessageAttachment.objects.select_related('message__order'),
            pk=pk,
            message__order__user=request.user,
        )

    if not att.file:
        raise Http404

    try:
        return FileResponse(
            att.file.open('rb'),
            as_attachment=True,
            filename=att.filename,
        )
    except (FileNotFoundError, OSError):
        raise Http404

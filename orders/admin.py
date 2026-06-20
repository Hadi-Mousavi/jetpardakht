from django.contrib import admin, messages
from django.db.models import Count, FileField, Q
from django.forms.widgets import ClearableFileInput
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Category, Order, OrderAttachment,
    OrderMessage, OrderMessageAttachment, SubCategory,
)
from .forms import ValidatedOrderAttachmentForm, ValidatedOrderMessageAttachmentForm


# ── Private-storage-safe file widget ──────────────────────────────────────────
#
# Problem: Django's ClearableFileInput.is_initial() contains:
#
#     return bool(value and getattr(value, 'url', False))
#
# PrivateFileSystemStorage sets base_url=None, so accessing .url raises
# ValueError (not AttributeError).  getattr's default only suppresses
# AttributeError, so the ValueError propagates and crashes the admin page.
#
# Fix: override is_initial() to check value.name instead of value.url.
# Returning False suppresses the "Currently: <link>" section in the widget
# template, so .url is never called.  Existing-file information is shown
# instead via the _file_info readonly column on each inline.

class PrivateFileWidget(ClearableFileInput):
    """
    ClearableFileInput that never calls file.url.

    Safe for use with PrivateFileSystemStorage (base_url=None).
    Always renders only the file-upload input; file metadata is shown
    in the companion _file_info readonly column instead.
    """

    def is_initial(self, value):
        # Detect an existing file by name only — never touch .url.
        return False


def _fmt_size(n_bytes):
    """Human-readable file size."""
    if n_bytes < 1024:
        return f'{n_bytes} B'
    if n_bytes < 1024 * 1024:
        return f'{n_bytes / 1024:.1f} KB'
    return f'{n_bytes / (1024 * 1024):.1f} MB'


def _order_att_info(obj, download_url_name):
    """
    Return a safe HTML snippet with filename, size, and a download link.

    Uses storage.size(name) rather than file.url — works with private storage.
    """
    if not obj.pk or not obj.file or not obj.file.name:
        return '—'

    filename = obj.filename          # .name.split('/')[-1] — no .url call

    try:
        size_str = _fmt_size(obj.file.size)   # calls storage.size(name), not .url
    except (FileNotFoundError, OSError, NotImplementedError):
        size_str = 'فایل روی دیسک موجود نیست'

    dl_url = reverse(download_url_name, args=[obj.pk])

    return format_html(
        '<div style="line-height:1.7;font-size:.85em">'
        '<a href="{}" target="_blank" style="font-weight:600;text-decoration:none">'
        '⬇ {}</a><br>'
        '<span style="color:#6c757d">{}</span>'
        '</div>',
        dl_url, filename, size_str,
    )


# ── Sub-model inlines ─────────────────────────────────────────────────────────

class SubCategoryInline(admin.TabularInline):
    model       = SubCategory
    extra       = 1
    fields      = ['title', 'description', 'is_active', 'display_order']
    ordering    = ['display_order', 'title']


class OrderAttachmentInline(admin.TabularInline):
    model           = OrderAttachment
    form            = ValidatedOrderAttachmentForm
    extra           = 0
    readonly_fields = ['_file_info', 'created_at']
    fields          = ['_file_info', 'file', 'title', 'uploaded_by', 'created_at']
    formfield_overrides = {
        FileField: {'widget': PrivateFileWidget},
    }

    @admin.display(description='فایل پیوست')
    def _file_info(self, obj):
        return _order_att_info(obj, 'order_attachment_download')


class OrderMessageAttachmentInline(admin.TabularInline):
    model           = OrderMessageAttachment
    form            = ValidatedOrderMessageAttachmentForm
    extra           = 0
    readonly_fields = ['_file_info', 'uploaded_at']
    fields          = ['_file_info', 'file', 'uploaded_at']
    formfield_overrides = {
        FileField: {'widget': PrivateFileWidget},
    }

    @admin.display(description='فایل پیوست')
    def _file_info(self, obj):
        return _order_att_info(obj, 'message_attachment_download')


class OrderMessageInline(admin.StackedInline):
    model           = OrderMessage
    extra           = 1
    readonly_fields = ['created_at', 'is_read']
    fields          = ['sender', 'message', 'is_read', 'created_at']
    ordering        = ['created_at']
    show_change_link = True


# ── Category ──────────────────────────────────────────────────────────────────

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display        = ['title', 'slug', 'is_active', 'display_order', '_sub_count', 'created_at']
    list_filter         = ['is_active']
    search_fields       = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}
    inlines             = [SubCategoryInline]
    list_editable       = ['is_active', 'display_order']

    @admin.display(description='تعداد زیر دسته‌ها')
    def _sub_count(self, obj):
        return obj.subcategories.count()


# ── SubCategory ───────────────────────────────────────────────────────────────

@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display  = ['title', 'category', 'is_active', 'display_order']
    list_filter   = ['is_active', 'category']
    search_fields = ['title', 'category__title']
    list_editable = ['is_active', 'display_order']


# ── Order — status badge colours ──────────────────────────────────────────────

_STATUS_BADGE_STYLES = {
    Order.STATUS_DRAFT:           ('background:#e9ecef;color:#495057', 'پیش‌نویس'),
    Order.STATUS_SUBMITTED:       ('background:#cfe2ff;color:#084298', 'ثبت شده'),
    Order.STATUS_UNDER_REVIEW:    ('background:#cff4fc;color:#055160', 'در حال بررسی'),
    Order.STATUS_WAITING_PAYMENT: ('background:#fff3cd;color:#664d03', 'در انتظار پرداخت'),
    Order.STATUS_IN_PROGRESS:     ('background:#d1ecf1;color:#0c5460', 'در حال انجام'),
    Order.STATUS_COMPLETED:       ('background:#d1e7dd;color:#0a3622', 'تکمیل شده'),
    Order.STATUS_REJECTED:        ('background:#f8d7da;color:#58151c', 'رد شده'),
    Order.STATUS_CANCELLED:       ('background:#e9ecef;color:#495057', 'لغو شده'),
}

_BADGE_BASE = (
    'display:inline-block;padding:3px 10px;border-radius:12px;'
    'font-size:0.78rem;font-weight:600;white-space:nowrap;letter-spacing:.02em'
)


# ── Order — bulk actions ───────────────────────────────────────────────────────

def _make_status_action(target_status, label, icon):
    """Factory that builds a bulk-action function for a given target status."""

    def action(modeladmin, request, queryset):
        count = queryset.exclude(status=target_status).update(status=target_status)
        messages.success(request, f'{count} سفارش به وضعیت «{label}» تغییر یافت.')

    action.short_description = f'{icon} {label}'
    action.__name__ = f'mark_as_{target_status}'
    return action


mark_as_under_review = _make_status_action(
    Order.STATUS_UNDER_REVIEW, 'در حال بررسی', '🔍',
)
mark_as_in_progress = _make_status_action(
    Order.STATUS_IN_PROGRESS, 'در حال انجام', '🚀',
)
mark_as_completed = _make_status_action(
    Order.STATUS_COMPLETED, 'تکمیل شده', '✅',
)


# ── Order ─────────────────────────────────────────────────────────────────────

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    # ── list columns ──────────────────────────────────────────────────────────
    list_display = [
        '_tracking_code',
        '_customer_name',
        'category',
        '_status_badge',
        '_assigned_admin_display',
        '_created_at_display',
    ]

    # ── filters ───────────────────────────────────────────────────────────────
    list_filter = [
        'status',
        'category',
        'assigned_admin',
        'created_at',
    ]

    # ── search ────────────────────────────────────────────────────────────────
    search_fields = [
        'order_number',
        'user__first_name',
        'user__last_name',
        'user__email',
        'user__national_id',
        'organization_name',
        'assigned_admin__email',
    ]

    # ── form ──────────────────────────────────────────────────────────────────
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    inlines         = [OrderAttachmentInline, OrderMessageInline]
    actions         = [mark_as_under_review, mark_as_in_progress, mark_as_completed]

    fieldsets = (
        ('شماره سفارش', {
            'fields': ('order_number',),
        }),
        ('کاربر', {
            'fields': ('user',),
        }),
        ('جزئیات سفارش', {
            'fields': (
                'category', 'subcategory',
                'organization_name', 'amount', 'currency',
                'deadline', 'description',
            ),
        }),
        ('یادداشت مشتری', {
            'fields': ('customer_note',),
        }),
        ('مدیریت', {
            'fields': ('status', 'assigned_admin', 'admin_note'),
        }),
        ('زمان‌بندی', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    # ── queryset ──────────────────────────────────────────────────────────────

    def get_queryset(self, request):
        # select_related eliminates per-row FK lookups for user, assigned_admin,
        # category, and subcategory — the four FKs touched in list columns.
        return (
            super().get_queryset(request)
            .select_related('user', 'assigned_admin', 'category', 'subcategory')
        )

    # ── changelist with stats card ────────────────────────────────────────────

    def changelist_view(self, request, extra_context=None):
        stats = Order.objects.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(
                status__in=[Order.STATUS_SUBMITTED, Order.STATUS_UNDER_REVIEW],
            )),
            in_progress=Count('id', filter=Q(status=Order.STATUS_IN_PROGRESS)),
            completed=Count('id', filter=Q(status=Order.STATUS_COMPLETED)),
        )
        extra_context = extra_context or {}
        extra_context['order_stats'] = stats
        return super().changelist_view(request, extra_context=extra_context)

    # ── display columns ───────────────────────────────────────────────────────

    @admin.display(description='کد پیگیری', ordering='order_number')
    def _tracking_code(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="font-family:monospace;font-weight:600;'
            'font-size:0.82rem;letter-spacing:.03em;color:#0d6efd">{}</a>',
            url, obj.order_number,
        )

    @admin.display(description='مشتری', ordering='user__last_name')
    def _customer_name(self, obj):
        full = obj.user.get_full_name() or obj.user.email
        return format_html(
            '<span style="font-weight:600">{}</span>'
            '<br><span style="font-size:0.78rem;color:#6c757d">{}</span>',
            full, obj.user.email,
        )

    @admin.display(description='وضعیت', ordering='status')
    def _status_badge(self, obj):
        style, label = _STATUS_BADGE_STYLES.get(
            obj.status,
            ('background:#e9ecef;color:#495057', obj.status_label),
        )
        return format_html(
            '<span style="{};{}">{}</span>',
            _BADGE_BASE, style, label,
        )

    @admin.display(description='مسئول سفارش', ordering='assigned_admin__last_name')
    def _assigned_admin_display(self, obj):
        if not obj.assigned_admin:
            return format_html('<span style="color:#adb5bd;font-size:0.82rem">—</span>')
        name = obj.assigned_admin.get_full_name() or obj.assigned_admin.email
        return format_html(
            '<span style="font-size:0.88rem;font-weight:600">{}</span>',
            name,
        )

    @admin.display(description='تاریخ ثبت', ordering='created_at')
    def _created_at_display(self, obj):
        return format_html(
            '<span style="font-size:0.82rem;color:#495057;white-space:nowrap">{}</span>',
            obj.created_at.strftime('%Y/%m/%d'),
        )


# ── OrderMessage (standalone, for search / direct access) ─────────────────────

@admin.register(OrderMessage)
class OrderMessageAdmin(admin.ModelAdmin):
    list_display    = ['order', 'sender', 'is_read', 'created_at', '_preview']
    list_filter     = ['is_read', 'created_at']
    search_fields   = ['order__order_number', 'sender__email', 'message']
    readonly_fields = ['created_at', 'is_read']
    inlines         = [OrderMessageAttachmentInline]

    @admin.display(description='پیام')
    def _preview(self, obj):
        return obj.message[:80] + ('…' if len(obj.message) > 80 else '')

from django.contrib import admin
from django.db.models import FileField
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
    # _file_info is readonly; 'file' uses PrivateFileWidget so .url is never called.
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
    # Same pattern: PrivateFileWidget for uploads; _file_info for existing files.
    readonly_fields = ['_file_info', 'uploaded_at']
    fields          = ['_file_info', 'file', 'uploaded_at']
    formfield_overrides = {
        FileField: {'widget': PrivateFileWidget},
    }

    @admin.display(description='فایل پیوست')
    def _file_info(self, obj):
        return _order_att_info(obj, 'message_attachment_download')


class OrderMessageInline(admin.StackedInline):
    model          = OrderMessage
    extra          = 1
    readonly_fields = ['created_at']
    fields         = ['sender', 'message', 'created_at']
    ordering       = ['created_at']
    show_change_link = True


# ── Category ──────────────────────────────────────────────────────────────────

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display       = ['title', 'slug', 'is_active', 'display_order', '_sub_count', 'created_at']
    list_filter        = ['is_active']
    search_fields      = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}
    inlines            = [SubCategoryInline]
    list_editable      = ['is_active', 'display_order']

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


# ── Order ─────────────────────────────────────────────────────────────────────

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display   = [
        'order_number', '_user_name', 'category', 'subcategory',
        '_status_badge', 'assigned_admin', 'created_at',
    ]
    list_filter    = ['status', 'category', 'subcategory', 'assigned_admin', 'created_at']
    search_fields  = [
        'order_number',
        'user__email', 'user__first_name', 'user__last_name',
        'organization_name',
        'assigned_admin__email', 'assigned_admin__username',
    ]
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    inlines         = [OrderAttachmentInline, OrderMessageInline]
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

    @admin.display(description='کاربر')
    def _user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email

    @admin.display(description='وضعیت')
    def _status_badge(self, obj):
        colors = {
            'draft':                    '#6c757d',
            'submitted':                '#0d6efd',
            'under_review':             '#0dcaf0',
            'waiting_customer_payment': '#ffc107',
            'in_progress':              '#0d6efd',
            'completed':                '#198754',
            'rejected':                 '#dc3545',
            'cancelled':                '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="'
            'background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:0.8em;white-space:nowrap'
            '">{}</span>',
            color, obj.status_label,
        )


# ── OrderMessage (standalone, for search / direct access) ─────────────────────

@admin.register(OrderMessage)
class OrderMessageAdmin(admin.ModelAdmin):
    list_display   = ['order', 'sender', 'created_at', '_preview']
    list_filter    = ['created_at']
    search_fields  = ['order__order_number', 'sender__email', 'message']
    readonly_fields = ['created_at']
    inlines        = [OrderMessageAttachmentInline]

    @admin.display(description='پیام')
    def _preview(self, obj):
        return obj.message[:80] + ('…' if len(obj.message) > 80 else '')

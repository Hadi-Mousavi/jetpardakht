from django.contrib import admin
from django.utils.html import format_html

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'tracking_code', 'name', 'phone', 'email', 'service_type',
        'amount', 'status', 'created_at', 'document_link',
    ]
    list_filter = ['status', 'service_type', 'created_at']
    search_fields = ['tracking_code', 'name', 'phone', 'email']
    readonly_fields = ['tracking_code', 'created_at', 'document_preview']
    fieldsets = (
        ('کد پیگیری', {
            'fields': ('tracking_code',),
        }),
        ('اطلاعات مشتری', {
            'fields': ('name', 'phone', 'email'),
        }),
        ('جزئیات سفارش', {
            'fields': ('service_type', 'amount', 'description', 'status'),
        }),
        ('مدرک پیوست', {
            'fields': ('document', 'document_preview'),
        }),
        ('زمان ثبت', {
            'fields': ('created_at',),
        }),
    )

    @admin.display(description='مدرک یا فایل پیوست')
    def document_link(self, obj):
        if obj.document:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.document.url,
                obj.document.name,
            )
        return '—'

    @admin.display(description='پیش‌نمایش فایل')
    def document_preview(self, obj):
        if not obj.document:
            return '—'

        url = obj.document.url
        name = obj.document.name

        if name.lower().endswith('.pdf'):
            return format_html(
                '<a href="{}" target="_blank">مشاهده PDF: {}</a>',
                url,
                name,
            )

        return format_html(
            '<a href="{}" target="_blank">'
            '<img src="{}" style="max-width:320px; border-radius:8px; border:1px solid #ddd;" />'
            '</a><br><a href="{}" target="_blank">{}</a>',
            url,
            url,
            url,
            name,
        )

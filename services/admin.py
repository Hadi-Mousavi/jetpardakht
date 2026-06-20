from django.contrib import admin
from django.utils.html import format_html

from .models import OrderFieldValue, Service, ServiceCategory, ServiceField


# ---------------------------------------------------------------------------
# ServiceField inline — embedded inside ServiceAdmin
# ---------------------------------------------------------------------------

class ServiceFieldInline(admin.TabularInline):
    model      = ServiceField
    extra      = 1
    fields     = (
        'sort_order', 'label', 'field_name', 'field_type',
        'is_required', 'placeholder', 'help_text', 'choices_json',
    )
    ordering   = ('sort_order', 'id')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('service')


# ---------------------------------------------------------------------------
# ServiceCategoryAdmin
# ---------------------------------------------------------------------------

@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display   = ('name', 'slug', '_icon_preview', 'is_active', 'sort_order', 'created_at')
    list_filter    = ('is_active',)
    search_fields  = ('name', 'slug', 'description')
    ordering       = ('sort_order', 'name')
    list_editable  = ('is_active', 'sort_order')

    @admin.display(description='آیکون')
    def _icon_preview(self, obj):
        if obj.icon:
            return format_html('<i class="{}"></i> {}', obj.icon, obj.icon)
        return '—'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('services')


# ---------------------------------------------------------------------------
# ServiceAdmin
# ---------------------------------------------------------------------------

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display   = (
        'name', 'category', 'slug',
        '_price_display', 'is_active', 'requires_kyc', 'requires_payment',
        'sort_order',
    )
    list_filter    = (
        'is_active', 'requires_kyc', 'requires_payment', 'category',
    )
    search_fields  = ('name', 'slug', 'short_description', 'description')
    ordering       = ('sort_order', 'name')
    list_editable  = ('is_active', 'sort_order')
    inlines        = [ServiceFieldInline]
    fieldsets      = (
        ('اطلاعات اصلی', {
            'fields': ('category', 'name', 'slug', 'icon', 'is_active', 'sort_order'),
        }),
        ('محتوا', {
            'fields': ('short_description', 'description'),
        }),
        ('قیمت‌گذاری', {
            'fields': ('base_price', 'currency'),
        }),
        ('الزامات', {
            'fields': ('requires_kyc', 'requires_payment'),
        }),
    )

    @admin.display(description='قیمت پایه')
    def _price_display(self, obj):
        return obj.price_display or '—'

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('category')
            .prefetch_related('fields')
        )


# ---------------------------------------------------------------------------
# OrderFieldValue — read-only admin for inspection / support
# ---------------------------------------------------------------------------

@admin.register(OrderFieldValue)
class OrderFieldValueAdmin(admin.ModelAdmin):
    list_display  = ('order', 'service_field', '_value_display', 'created_at')
    list_filter   = ('service_field__service',)
    search_fields = ('order__order_number', 'service_field__label', 'value_text')
    readonly_fields = ('order', 'service_field', 'value_text', 'value_file', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='مقدار')
    def _value_display(self, obj):
        if obj.is_file:
            return format_html('<code>{}</code>', obj.display_value)
        return obj.value_text[:80] or '—'

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('order', 'service_field', 'service_field__service')
        )

from django.contrib import admin

from .models import KYCProfile


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'national_id',
        'date_of_birth',
        'status',
        'created_at',
        'updated_at',
    ]
    list_filter = ['status']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'national_id']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('user', 'status'),
        }),
        ('اطلاعات هویتی', {
            'fields': ('national_id', 'date_of_birth'),
        }),
        ('تاریخ‌ها', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

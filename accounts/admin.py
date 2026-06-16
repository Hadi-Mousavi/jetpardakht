from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OTPCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin for the custom User model.

    Extends Django's built-in UserAdmin to remove the username field
    and surface email, phone, and verification flags instead.
    BaseUserAdmin already provides password change forms, permission
    management, and group/permission filter_horizontal widgets.
    """

    list_display = [
        'email', 'first_name', 'last_name', 'phone',
        'is_active', 'is_email_verified', 'is_phone_verified',
        'is_staff', 'created_at',
    ]
    list_filter = [
        'is_active', 'is_staff', 'is_superuser',
        'is_email_verified', 'is_phone_verified',
        'created_at',
    ]
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at', 'last_login']
    filter_horizontal = ['groups', 'user_permissions']

    fieldsets = (
        (None, {
            'fields': ('email', 'password'),
        }),
        ('اطلاعات شخصی', {
            'fields': ('first_name', 'last_name', 'phone'),
        }),
        ('وضعیت حساب', {
            'fields': ('is_active', 'is_email_verified', 'is_phone_verified'),
        }),
        ('دسترسی‌ها', {
            'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        ('تاریخ‌ها', {
            'fields': ('last_login', 'created_at', 'updated_at'),
        }),
    )

    # Fields shown on the "Add user" form in admin
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    """
    Read-only admin view for OTP codes.
    Useful for debugging and support — no creation from admin.
    """

    list_display = [
        'phone', 'purpose', 'user', 'attempt_count',
        'created_at', 'expires_at', 'consumed_at',
    ]
    list_filter = ['purpose']
    search_fields = ['phone']
    readonly_fields = [
        'phone', 'code_hash', 'purpose', 'user',
        'created_at', 'expires_at', 'consumed_at', 'attempt_count',
    ]
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

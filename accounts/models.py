from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for JetPay24.

    Email is the primary login identifier; no username field exists.
    PermissionsMixin provides is_superuser, groups, and user_permissions,
    which keeps full Django admin and permission-system compatibility.
    """

    email = models.EmailField(
        unique=True,
        verbose_name='ایمیل',
    )
    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        verbose_name='شماره موبایل',
    )
    first_name = models.CharField(
        max_length=60,
        verbose_name='نام',
    )
    last_name = models.CharField(
        max_length=60,
        verbose_name='نام خانوادگی',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='فعال',
        help_text='غیرفعال کردن به جای حذف کاربر.',
    )
    is_staff = models.BooleanField(
        default=False,
        verbose_name='کارمند',
        help_text='دسترسی به پنل مدیریت.',
    )
    is_email_verified = models.BooleanField(
        default=False,
        verbose_name='ایمیل تأیید شده',
    )
    is_phone_verified = models.BooleanField(
        default=False,
        verbose_name='موبایل تأیید شده',
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاریخ ثبت',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='آخرین ویرایش',
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = 'کاربر'
        verbose_name_plural = 'کاربران'
        ordering = ['-created_at']

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def get_short_name(self):
        return self.first_name


class OTPCode(models.Model):
    """
    Schema stub for future mobile OTP login.

    Deliberately has no views or URL wiring in Phase 1.
    The table is created now so that adding OTP flows later
    requires only views/URLs, not a new migration.

    Security notes:
    - code_hash stores a hashed code, never plaintext.
    - attempt_count enforces brute-force limits at the application layer.
    - purpose prevents cross-flow token reuse (e.g. a login OTP cannot
      be accepted as a password-reset OTP).
    """

    PURPOSE_LOGIN = 'LOGIN'
    PURPOSE_REGISTER = 'REGISTER'
    PURPOSE_PHONE_VERIFY = 'PHONE_VERIFY'
    PURPOSE_PASSWORD_RESET = 'PASSWORD_RESET'

    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, 'ورود'),
        (PURPOSE_REGISTER, 'ثبت‌نام'),
        (PURPOSE_PHONE_VERIFY, 'تأیید موبایل'),
        (PURPOSE_PASSWORD_RESET, 'بازیابی رمز عبور'),
    ]

    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='otp_codes',
        verbose_name='کاربر',
    )
    phone = models.CharField(
        max_length=20,
        verbose_name='شماره موبایل',
    )
    code_hash = models.CharField(
        max_length=128,
        verbose_name='کد هش‌شده',
    )
    purpose = models.CharField(
        max_length=20,
        choices=PURPOSE_CHOICES,
        verbose_name='هدف',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاریخ ایجاد',
    )
    expires_at = models.DateTimeField(
        verbose_name='تاریخ انقضا',
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاریخ استفاده',
    )
    attempt_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='تعداد تلاش',
    )

    class Meta:
        verbose_name = 'کد یکبار مصرف'
        verbose_name_plural = 'کدهای یکبار مصرف'
        indexes = [
            models.Index(fields=['phone', 'purpose'], name='accounts_otpcode_phone_purpose_idx'),
        ]

    def __str__(self):
        return f'{self.phone} — {self.get_purpose_display()}'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_consumed(self):
        return self.consumed_at is not None

    @property
    def is_valid(self):
        return not self.is_expired and not self.is_consumed

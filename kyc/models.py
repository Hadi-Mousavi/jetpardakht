from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator


class KYCProfile(models.Model):
    """
    Stores identity-verification data for a user.

    Status lifecycle:
        not_submitted  →  pending  →  approved
                                   ↘  rejected  →  pending (re-submission)

    Lock rules:
        not_submitted  →  editable, uploads allowed
        rejected       →  editable, uploads allowed
        pending        →  READ-ONLY (under review)
        approved       →  READ-ONLY (permanently locked)
    """

    STATUS_NOT_SUBMITTED = 'not_submitted'
    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_NOT_SUBMITTED, 'تکمیل نشده'),
        (STATUS_PENDING,       'در انتظار بررسی'),
        (STATUS_APPROVED,      'تأیید شده'),
        (STATUS_REJECTED,      'رد شده'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='kyc_profile',
        verbose_name='کاربر',
    )
    national_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        verbose_name='کد ملی',
        validators=[
            RegexValidator(
                regex=r'^[0-9]{10}$',
                message='کد ملی باید دقیقا ۱۰ رقم باشد.'
            )
        ],
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        verbose_name='تاریخ تولد',
    )
    national_id_image = models.ImageField(
        upload_to='kyc/documents/',
        null=True,
        blank=True,
        verbose_name='تصویر کارت ملی',
    )
    selfie_image = models.ImageField(
        upload_to='kyc/selfies/',
        null=True,
        blank=True,
        verbose_name='سلفی با کارت ملی',
    )
    status = models.CharField(
        max_length=13,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_SUBMITTED,
        db_index=True,
        verbose_name='وضعیت',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت')
    updated_at = models.DateTimeField(auto_now=True,     verbose_name='آخرین ویرایش')

    class Meta:
        verbose_name = 'پروفایل احراز هویت'
        verbose_name_plural = 'پروفایل‌های احراز هویت'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='kyc_status_created_idx'),
        ]

    def __str__(self):
        return f'{self.user} — {self.get_status_display()}'

    # ── status helpers ─────────────────────────────────────────────────────

    @property
    def is_not_submitted(self):
        return self.status == self.STATUS_NOT_SUBMITTED

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    @property
    def is_rejected(self):
        return self.status == self.STATUS_REJECTED

    @property
    def is_locked(self):
        """True when the form must be read-only (pending review or fully approved)."""
        return self.status in (self.STATUS_PENDING, self.STATUS_APPROVED)


class KYCSiteSettings(models.Model):
    """
    Singleton that stores admin-managed site-wide KYC settings.
    Only one row should exist; use KYCSiteSettings.get() to retrieve it.
    """

    guide_image = models.ImageField(
        upload_to='kyc/guide/',
        null=True,
        blank=True,
        verbose_name='تصویر راهنما',
        help_text='این تصویر در صفحه احراز هویت کاربران نمایش داده می‌شود.',
    )

    class Meta:
        verbose_name = 'تنظیمات احراز هویت'
        verbose_name_plural = 'تنظیمات احراز هویت'

    def __str__(self):
        return 'تنظیمات احراز هویت'

    @classmethod
    def get(cls):
        """Return the singleton settings row, or None if not yet created."""
        return cls.objects.first()

from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator


class KYCProfile(models.Model):
    """
    Stores identity-verification data for a user.

    Deliberately separated from the User model so that KYC state can evolve
    independently (new document types, reviewer notes, re-submission flows)
    without touching the core auth model.

    A profile row is created on first KYC submission; until then no row
    exists for a user, which is a clean sentinel for "never submitted".

    Status lifecycle:  (none) → PENDING → APPROVED
                                        ↘ REJECTED → PENDING (re-submission)
    """

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'در انتظار بررسی'),
        (STATUS_APPROVED, 'تأیید شده'),
        (STATUS_REJECTED, 'رد شده'),
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
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name='وضعیت',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاریخ ثبت',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='آخرین ویرایش',
    )

    class Meta:
        verbose_name = 'پروفایل KYC'
        verbose_name_plural = 'پروفایل‌های KYC'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='kyc_status_created_idx'),
        ]

    def __str__(self):
        return f'{self.user} — {self.get_status_display()}'

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    @property
    def is_rejected(self):
        return self.status == self.STATUS_REJECTED

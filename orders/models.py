import random
import string

from django.db import models

_STATUS_FA = {
    'NEW': 'در انتظار بررسی',
    'PROCESSING': 'در حال پردازش',
    'COMPLETED': 'تکمیل شده',
    'CANCELLED': 'لغو شده',
}

_SERVICE_FA = {
    'APPLICATION_FEE': 'پرداخت اپلیکیشن فی دانشگاه',
    'TUITION': 'پرداخت شهریه دانشگاه',
    'TOEFL': 'ثبت نام آزمون TOEFL',
    'GRE': 'ثبت نام آزمون GRE',
    'VISA': 'پرداخت هزینه سفارت',
    'OTHER': 'سایر پرداخت‌های بین‌المللی',
}


def _new_tracking_code():
    chars = string.ascii_uppercase + string.digits
    return 'JP24-' + ''.join(random.choices(chars, k=6))


class Order(models.Model):

    STATUS_CHOICES = [
        ('NEW', 'New'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    SERVICE_CHOICES = [
        ('APPLICATION_FEE', 'Application Fee'),
        ('TUITION', 'Tuition'),
        ('TOEFL', 'TOEFL'),
        ('GRE', 'GRE'),
        ('VISA', 'Visa'),
        ('OTHER', 'Other'),
    ]

    tracking_code = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        verbose_name='کد پیگیری',
    )

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField()

    service_type = models.CharField(
        max_length=30,
        choices=SERVICE_CHOICES
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    description = models.TextField(blank=True)

    document = models.FileField(
        upload_to='orders/',
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='NEW'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            code = _new_tracking_code()
            while Order.objects.filter(tracking_code=code).exists():
                code = _new_tracking_code()
            self.tracking_code = code
        super().save(*args, **kwargs)

    @property
    def status_fa(self):
        return _STATUS_FA.get(self.status, self.status)

    @property
    def service_type_fa(self):
        return _SERVICE_FA.get(self.service_type, self.service_type)

    def __str__(self):
        return f'{self.tracking_code} — {self.name}'
"""
services/models.py

Slug safety contract
--------------------
Both ServiceCategory.slug and Service.slug are ASCII-only slugs that are
safe for use in Django URL patterns that use the built-in <slug:slug>
converter (regex: [-a-zA-Z0-9_]+).

Auto-generation rules (applied in .save()):
  1. If slug is blank → auto-generate from the model's name field.
  2. If slug contains any non-ASCII character → treat as invalid and
     auto-generate (handles rows that were created before this fix).
  3. Auto-generation:
       a. slugify(name)  — strips non-ASCII, lowercases, replaces spaces/-
       b. If slugify returns '' (pure Persian/non-ASCII name):
            - Use pk-based fallback if pk is known:  "service-{pk}"
            - Otherwise use UUID fallback:            "service-{uuid8}"
       c. Guarantee uniqueness by appending a numeric suffix as needed.
  4. Manually provided ASCII slugs are preserved as-is.

Model validation (full_clean / clean()):
  - If a non-empty slug is provided and contains non-ASCII chars →
    ValidationError.  Prevents such slugs reaching the database at all
    via Django forms and the admin.
"""

import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from orders.storage import PrivateFileSystemStorage

# Regex that matches only valid ASCII slug characters.
_ASCII_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _is_valid_ascii_slug(value):
    """Return True iff *value* is a non-empty, ASCII-only slug."""
    return bool(value and _ASCII_SLUG_RE.match(value))


# ---------------------------------------------------------------------------
# ServiceCategory
# ---------------------------------------------------------------------------

class ServiceCategory(models.Model):
    name        = models.CharField(max_length=200, verbose_name='نام دسته‌بندی')
    slug        = models.SlugField(
        max_length=200, unique=True,
        # allow_unicode intentionally omitted (defaults to False) so Django's
        # own SlugField validator also rejects non-ASCII slugs.
        blank=True,  # allows save() to auto-generate when not supplied
        verbose_name='اسلاگ',
        help_text=(
            'فقط حروف انگلیسی، اعداد، خط تیره و زیرخط مجاز است. '
            'اگر خالی بگذارید، به‌صورت خودکار از نام تولید می‌شود.'
        ),
    )
    icon        = models.CharField(
        max_length=100, blank=True,
        verbose_name='آیکون',
        help_text='نام آیکون Bootstrap Icons — مثال: bi-globe',
    )
    description = models.TextField(blank=True, verbose_name='توضیحات')
    is_active   = models.BooleanField(default=True, verbose_name='فعال')
    sort_order  = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')

    class Meta:
        ordering        = ['sort_order', 'name']
        verbose_name    = 'دسته‌بندی سرویس'
        verbose_name_plural = 'دسته‌بندی‌های سرویس'

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Slug generation helpers
    # ------------------------------------------------------------------

    def _generate_slug(self):
        """Return a unique, ASCII-only slug derived from self.name."""
        base = slugify(self.name)   # allow_unicode defaults to False → ASCII
        if not base:
            # Purely non-ASCII name (e.g. Persian-only).
            base = f'category-{self.pk}' if self.pk else f'category-{uuid.uuid4().hex[:8]}'

        slug = base
        qs = ServiceCategory.objects.exclude(pk=self.pk) if self.pk else ServiceCategory.objects.all()
        counter = 1
        while qs.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        return slug

    def clean(self):
        """Reject explicitly supplied slugs that contain non-ASCII chars."""
        if self.slug and not _is_valid_ascii_slug(self.slug):
            raise ValidationError({
                'slug': (
                    'اسلاگ فقط می‌تواند شامل حروف انگلیسی، اعداد، '
                    'خط تیره (-) و زیرخط (_) باشد.'
                )
            })

    def save(self, *args, **kwargs):
        # Auto-generate when blank or when an invalid (non-ASCII) slug slips
        # through without going via full_clean() (e.g. direct ORM calls).
        if not _is_valid_ascii_slug(self.slug):
            self.slug = self._generate_slug()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class Service(models.Model):
    category          = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name='services',
        verbose_name='دسته‌بندی',
    )
    name              = models.CharField(max_length=200, verbose_name='نام سرویس')
    slug              = models.SlugField(
        max_length=200, unique=True,
        blank=True,   # auto-generated in save() when not supplied
        verbose_name='اسلاگ',
        help_text=(
            'فقط حروف انگلیسی، اعداد، خط تیره و زیرخط مجاز است. '
            'اگر خالی بگذارید، به‌صورت خودکار از نام تولید می‌شود.'
        ),
    )
    short_description = models.TextField(blank=True, verbose_name='توضیح کوتاه')
    description       = models.TextField(blank=True, verbose_name='توضیح کامل')
    icon              = models.CharField(
        max_length=100, blank=True,
        verbose_name='آیکون',
        help_text='نام آیکون Bootstrap Icons — مثال: bi-mortarboard-fill',
    )
    is_active         = models.BooleanField(default=True, verbose_name='فعال')
    requires_kyc      = models.BooleanField(
        default=True, verbose_name='نیاز به احراز هویت',
    )
    requires_payment  = models.BooleanField(
        default=False, verbose_name='نیاز به پرداخت',
    )
    base_price        = models.DecimalField(
        max_digits=14, decimal_places=2,
        null=True, blank=True,
        verbose_name='قیمت پایه',
    )
    currency          = models.CharField(
        max_length=10, blank=True, default='USD',
        verbose_name='ارز',
    )
    sort_order        = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')
    created_at        = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')

    class Meta:
        ordering        = ['sort_order', 'name']
        verbose_name    = 'سرویس'
        verbose_name_plural = 'سرویس‌ها'

    def __str__(self):
        return self.name

    @property
    def price_display(self):
        if self.base_price:
            return f'{self.base_price} {self.currency}'.strip()
        return ''

    # ------------------------------------------------------------------
    # Slug generation helpers
    # ------------------------------------------------------------------

    def _generate_slug(self):
        """Return a unique, ASCII-only slug derived from self.name."""
        base = slugify(self.name)   # allow_unicode=False (default) → ASCII
        if not base:
            # Purely non-ASCII name (e.g. Persian-only).
            # Prefer a stable pk-based slug; fall back to UUID for new objects.
            base = f'service-{self.pk}' if self.pk else f'service-{uuid.uuid4().hex[:8]}'

        slug = base
        qs = Service.objects.exclude(pk=self.pk) if self.pk else Service.objects.all()
        counter = 1
        while qs.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        return slug

    def clean(self):
        """Reject explicitly supplied slugs that contain non-ASCII chars."""
        if self.slug and not _is_valid_ascii_slug(self.slug):
            raise ValidationError({
                'slug': (
                    'اسلاگ فقط می‌تواند شامل حروف انگلیسی، اعداد، '
                    'خط تیره (-) و زیرخط (_) باشد.'
                )
            })

    def save(self, *args, **kwargs):
        # Auto-generate when blank or when a non-ASCII slug slips through
        # without going via full_clean() (e.g. direct ORM / bulk create).
        if not _is_valid_ascii_slug(self.slug):
            self.slug = self._generate_slug()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# ServiceField
# ---------------------------------------------------------------------------

class ServiceField(models.Model):
    """
    One record per dynamic form field on a Service.

    Admins create these records in the Service admin inline to define what
    data the customer must supply when placing an order for that service.
    """

    FIELD_TEXT     = 'text'
    FIELD_TEXTAREA = 'textarea'
    FIELD_NUMBER   = 'number'
    FIELD_EMAIL    = 'email'
    FIELD_FILE     = 'file'
    FIELD_SELECT   = 'select'
    FIELD_DATE     = 'date'
    FIELD_URL      = 'url'

    FIELD_TYPE_CHOICES = [
        (FIELD_TEXT,     'متن کوتاه'),
        (FIELD_TEXTAREA, 'متن بلند'),
        (FIELD_NUMBER,   'عدد'),
        (FIELD_EMAIL,    'ایمیل'),
        (FIELD_FILE,     'فایل (PDF / تصویر)'),
        (FIELD_SELECT,   'انتخاب از لیست'),
        (FIELD_DATE,     'تاریخ'),
        (FIELD_URL,      'آدرس وب'),
    ]

    service     = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='fields',
        verbose_name='سرویس',
    )
    label       = models.CharField(max_length=200, verbose_name='عنوان فیلد')
    field_name  = models.SlugField(
        max_length=100, allow_unicode=False,
        verbose_name='نام فنی فیلد',
        help_text='شناسه‌ای کوتاه و بدون فاصله — مثال: university_name',
    )
    field_type  = models.CharField(
        max_length=20, choices=FIELD_TYPE_CHOICES,
        default=FIELD_TEXT,
        verbose_name='نوع فیلد',
    )
    placeholder = models.CharField(
        max_length=300, blank=True,
        verbose_name='متن راهنما (placeholder)',
    )
    help_text   = models.CharField(
        max_length=500, blank=True,
        verbose_name='راهنمای زیر فیلد',
    )
    is_required = models.BooleanField(default=True, verbose_name='الزامی')
    sort_order  = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')
    choices_json = models.TextField(
        blank=True,
        verbose_name='گزینه‌های انتخابی (JSON)',
        help_text=(
            'فقط برای نوع «انتخاب از لیست». '
            'آرایه JSON — مثال: ["گزینه ۱", "گزینه ۲", "گزینه ۳"]'
        ),
    )

    class Meta:
        ordering        = ['sort_order', 'id']
        unique_together = [('service', 'field_name')]
        verbose_name    = 'فیلد سرویس'
        verbose_name_plural = 'فیلدهای سرویس'

    def __str__(self):
        return f'{self.service.name} — {self.label}'

    def parsed_choices(self):
        """Return list of (value, label) tuples from choices_json, or []."""
        import json
        if not self.choices_json:
            return []
        try:
            raw = json.loads(self.choices_json)
            if isinstance(raw, list):
                return [(str(c), str(c)) for c in raw]
        except (json.JSONDecodeError, TypeError):
            pass
        return []


# ---------------------------------------------------------------------------
# OrderFieldValue
# ---------------------------------------------------------------------------

class OrderFieldValue(models.Model):
    """
    One record per submitted dynamic field value, linked to an Order.

    Created in a single transaction alongside the Order in the service
    order submission view.  file values are stored in private storage;
    text/number/date/etc. are stored in value_text.
    """

    order         = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='field_values',
        verbose_name='سفارش',
    )
    service_field = models.ForeignKey(
        ServiceField,
        on_delete=models.PROTECT,
        related_name='submitted_values',
        verbose_name='فیلد سرویس',
    )
    value_text    = models.TextField(blank=True, verbose_name='مقدار متنی')
    value_file    = models.FileField(
        storage=PrivateFileSystemStorage(),
        upload_to='services/submissions/%Y/%m/',
        null=True, blank=True,
        verbose_name='فایل بارگذاری‌شده',
    )
    created_at    = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت')

    class Meta:
        ordering        = ['service_field__sort_order', 'service_field__id']
        verbose_name    = 'مقدار فیلد سفارش'
        verbose_name_plural = 'مقادیر فیلدهای سفارش'

    def __str__(self):
        return f'{self.order.order_number} — {self.service_field.label}'

    @property
    def display_value(self):
        """Return a string suitable for display (text or filename)."""
        if self.value_file and self.value_file.name:
            return self.value_file.name.split('/')[-1]
        return self.value_text

    @property
    def is_file(self):
        return bool(self.value_file and self.value_file.name)

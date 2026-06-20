from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .storage import PrivateFileSystemStorage


# ---------------------------------------------------------------------------
# Concurrency-safe order number generation
# ---------------------------------------------------------------------------
# Algorithm: dedicated OrderCounter row per calendar year, locked with
# SELECT FOR UPDATE inside an atomic block.
#
# Why this approach?
#   - A naive MAX()+1 query has a race window: two concurrent transactions
#     both read the same MAX value and generate the same number.
#   - SELECT FOR UPDATE on a single counter row serialises all concurrent
#     increments for the same year.  One transaction holds the lock; others
#     queue behind it.
#   - unique=True on Order.order_number is kept as a DB-level safety net.
#   - The inner savepoint handles the very first order of each new year:
#     two simultaneous requests both try to INSERT the counter row; only
#     one succeeds, the other's savepoint rolls back (IntegrityError caught),
#     and both then proceed to the SELECT FOR UPDATE path safely.
# ---------------------------------------------------------------------------


def _generate_order_number():
    """
    Return the next unique order number for the current year.

    Format: JP24-YYYY-NNNNNN  (e.g. JP24-2026-000042)

    Concurrency-safe: uses a per-year OrderCounter row locked with
    SELECT FOR UPDATE so no two concurrent calls can produce the same number.
    """
    year = timezone.now().year

    with transaction.atomic():
        # Attempt to create the year-counter row. If another transaction
        # already created it (race on the very first order of the year),
        # the IntegrityError is swallowed inside the inner savepoint and
        # execution continues — the row is guaranteed to exist after this block.
        try:
            with transaction.atomic():          # inner savepoint
                OrderCounter.objects.create(year=year, last_seq=0)
        except IntegrityError:
            pass   # Row already exists — proceed to the lock below.

        # Acquire a row-level lock on the counter.
        # Any concurrent transaction that reaches this line will block until
        # the current transaction commits and releases the lock.
        counter = OrderCounter.objects.select_for_update().get(year=year)
        counter.last_seq += 1
        counter.save(update_fields=['last_seq'])

    return f'JP24-{year}-{counter.last_seq:06d}'


class OrderCounter(models.Model):
    """
    Per-year sequence counter used by _generate_order_number().

    One row per calendar year.  The row is locked with SELECT FOR UPDATE
    before incrementing so no two concurrent transactions can generate the
    same sequence number.

    This model is intentionally simple — it has no FK dependencies and is
    only ever accessed inside _generate_order_number().
    """

    year     = models.IntegerField(unique=True, verbose_name='سال')
    last_seq = models.IntegerField(default=0,   verbose_name='آخرین شماره')

    class Meta:
        verbose_name        = 'شمارنده سفارش'
        verbose_name_plural = 'شمارنده‌های سفارش'

    def __str__(self):
        return f'JP24-{self.year}-{self.last_seq:06d}'


class Category(models.Model):
    title         = models.CharField(max_length=200, verbose_name='عنوان')
    slug          = models.SlugField(max_length=200, unique=True, allow_unicode=True, verbose_name='اسلاگ')
    is_active     = models.BooleanField(default=True, verbose_name='فعال')
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')
    created_at    = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')

    class Meta:
        ordering        = ['display_order', 'title']
        verbose_name    = 'دسته‌بندی'
        verbose_name_plural = 'دسته‌بندی‌ها'

    def __str__(self):
        return self.title


class SubCategory(models.Model):
    category      = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='subcategories', verbose_name='دسته‌بندی',
    )
    title         = models.CharField(max_length=200, verbose_name='عنوان')
    description   = models.TextField(blank=True, verbose_name='توضیحات')
    is_active     = models.BooleanField(default=True, verbose_name='فعال')
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')

    class Meta:
        ordering        = ['display_order', 'title']
        verbose_name    = 'زیر دسته‌بندی'
        verbose_name_plural = 'زیر دسته‌بندی‌ها'

    def __str__(self):
        return f'{self.category.title} / {self.title}'


class Order(models.Model):

    STATUS_DRAFT             = 'draft'
    STATUS_SUBMITTED         = 'submitted'
    STATUS_UNDER_REVIEW      = 'under_review'
    STATUS_WAITING_PAYMENT   = 'waiting_customer_payment'
    STATUS_PAYMENT_REJECTED  = 'payment_rejected'
    STATUS_IN_PROGRESS       = 'in_progress'
    STATUS_WAITING_CUSTOMER  = 'waiting_customer'
    STATUS_COMPLETED         = 'completed'
    STATUS_REJECTED          = 'rejected'
    STATUS_CANCELLED         = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT,            'پیش‌نویس'),
        (STATUS_SUBMITTED,        'ثبت شده'),
        (STATUS_UNDER_REVIEW,     'در حال بررسی'),
        (STATUS_WAITING_PAYMENT,  'در انتظار پرداخت'),
        (STATUS_PAYMENT_REJECTED, 'پرداخت رد شده'),
        (STATUS_IN_PROGRESS,      'در حال انجام'),
        (STATUS_WAITING_CUSTOMER, 'منتظر اقدام مشتری'),
        (STATUS_COMPLETED,        'تکمیل شده'),
        (STATUS_REJECTED,         'رد شده'),
        (STATUS_CANCELLED,        'لغو شده'),
    ]

    # Maps status → Bootstrap colour token
    STATUS_COLORS = {
        STATUS_DRAFT:            'secondary',
        STATUS_SUBMITTED:        'primary',
        STATUS_UNDER_REVIEW:     'info',
        STATUS_WAITING_PAYMENT:  'warning',
        STATUS_PAYMENT_REJECTED: 'danger',
        STATUS_IN_PROGRESS:      'primary',
        STATUS_WAITING_CUSTOMER: 'warning',
        STATUS_COMPLETED:        'success',
        STATUS_REJECTED:         'danger',
        STATUS_CANCELLED:        'secondary',
    }

    order_number      = models.CharField(
        max_length=20, unique=True, editable=False,
        verbose_name='شماره سفارش',
    )
    user              = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
        verbose_name='کاربر',
    )
    category          = models.ForeignKey(
        Category, on_delete=models.PROTECT, verbose_name='دسته‌بندی',
    )
    subcategory       = models.ForeignKey(
        SubCategory, on_delete=models.PROTECT, verbose_name='زیر دسته‌بندی',
    )
    organization_name = models.CharField(
        max_length=300, blank=True, verbose_name='نام سازمان / دانشگاه',
    )
    amount            = models.DecimalField(
        max_digits=14, decimal_places=2,
        null=True, blank=True, verbose_name='مبلغ',
    )
    currency          = models.CharField(
        max_length=10, blank=True, verbose_name='ارز',
        help_text='مثال: USD, EUR, CAD',
    )
    deadline          = models.DateField(
        null=True, blank=True, verbose_name='ددلاین',
    )
    description       = models.TextField(verbose_name='توضیحات')
    customer_note     = models.TextField(blank=True, verbose_name='یادداشت مشتری')
    status            = models.CharField(
        max_length=30, choices=STATUS_CHOICES,
        default=STATUS_SUBMITTED, db_index=True,
        verbose_name='وضعیت',
    )
    service           = models.ForeignKey(
        'services.Service',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='orders',
        verbose_name='سرویس',
    )
    admin_note        = models.TextField(blank=True, verbose_name='یادداشت ادمین')
    assigned_admin    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_orders',
        limit_choices_to={'is_staff': True},
        verbose_name='مسئول سفارش',
    )
    created_at        = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')
    updated_at        = models.DateTimeField(auto_now=True, verbose_name='آخرین بروزرسانی')

    class Meta:
        ordering        = ['-created_at']
        verbose_name    = 'سفارش'
        verbose_name_plural = 'سفارش‌ها'

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = _generate_order_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.order_number} — {self.user}'

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def status_label(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)


class OrderAttachment(models.Model):
    order       = models.ForeignKey(
        Order, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='سفارش',
    )
    file        = models.FileField(
        storage=PrivateFileSystemStorage(),
        upload_to='orders/attachments/%Y/%m/',
        verbose_name='فایل',
    )
    title       = models.CharField(max_length=200, blank=True, verbose_name='عنوان')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        verbose_name='بارگذاری توسط',
    )
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ بارگذاری')

    class Meta:
        ordering        = ['-created_at']
        verbose_name    = 'پیوست سفارش'
        verbose_name_plural = 'پیوست‌های سفارش'

    def __str__(self):
        return f'{self.order.order_number} — {self.title or self.file.name}'

    @property
    def filename(self):
        return self.file.name.split('/')[-1]


class OrderMessage(models.Model):
    order      = models.ForeignKey(
        Order, on_delete=models.CASCADE,
        related_name='messages', verbose_name='سفارش',
    )
    sender     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        verbose_name='فرستنده',
    )
    message    = models.TextField(verbose_name='پیام')
    is_read    = models.BooleanField(default=False, verbose_name='خوانده شده')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ارسال')

    class Meta:
        ordering        = ['created_at']
        verbose_name    = 'پیام سفارش'
        verbose_name_plural = 'پیام‌های سفارش'

    def __str__(self):
        return f'{self.order.order_number} — {self.sender}'

    @property
    def is_from_staff(self):
        return self.sender and self.sender.is_staff

    def save(self, *args, **kwargs):
        if self.sender and not self.sender.is_staff:
            self.is_read = True
        super().save(*args, **kwargs)


class OrderMessageAttachment(models.Model):
    message     = models.ForeignKey(
        OrderMessage, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='پیام',
    )
    file        = models.FileField(
        storage=PrivateFileSystemStorage(),
        upload_to='orders/messages/%Y/%m/',
        verbose_name='فایل',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ بارگذاری')

    class Meta:
        verbose_name    = 'پیوست پیام'
        verbose_name_plural = 'پیوست‌های پیام'

    def __str__(self):
        return f'{self.message.order.order_number} — {self.file.name}'

    @property
    def filename(self):
        return self.file.name.split('/')[-1]


class OrderStatusHistory(models.Model):
    """
    Immutable audit log of every admin-initiated status transition.

    Created by OrderAdmin.save_model() whenever the order status changes.
    Used to:
      - Render a detailed timeline on the order detail page.
      - Show customers the reason/note for each status change.
      - Provide an audit trail for support staff.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_history',
        verbose_name='سفارش',
    )
    old_status = models.CharField(
        max_length=30,
        verbose_name='وضعیت قبلی',
    )
    new_status = models.CharField(
        max_length=30,
        verbose_name='وضعیت جدید',
        db_index=True,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='status_changes',
        limit_choices_to={'is_staff': True},
        verbose_name='تغییر داده‌شده توسط',
    )
    note = models.TextField(
        blank=True,
        verbose_name='یادداشت تغییر وضعیت',
        help_text='این یادداشت برای مشتری قابل مشاهده است.',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاریخ تغییر',
    )

    class Meta:
        ordering        = ['-created_at', '-id']
        verbose_name    = 'تاریخچه وضعیت'
        verbose_name_plural = 'تاریخچه وضعیت‌ها'

    def __str__(self):
        return (
            f'{self.order.order_number}: '
            f'{self.old_status} → {self.new_status}'
        )

    @property
    def new_status_label(self):
        return dict(Order.STATUS_CHOICES).get(self.new_status, self.new_status)

    @property
    def old_status_label(self):
        return dict(Order.STATUS_CHOICES).get(self.old_status, self.old_status)

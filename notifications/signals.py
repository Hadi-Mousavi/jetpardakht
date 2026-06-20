from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from kyc.models import KYCProfile
from orders.models import Order, OrderMessage

from .models import Notification
from .services import create_notification


@receiver(pre_save, sender=Order)
def _cache_order_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._previous_status = (
                Order.objects.filter(pk=instance.pk)
                .values_list('status', flat=True)
                .first()
            )
        except Order.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(post_save, sender=Order)
def _notify_order_events(sender, instance, created, **kwargs):
    if created:
        # Service orders get a dedicated notification type.
        if getattr(instance, 'service_id', None):
            create_notification(
                user=instance.user,
                title='سفارش جدید شما ثبت شد 🛍️',
                message=f'سفارش جدید شما ثبت شد.',
                notification_type=Notification.TYPE_SERVICE_ORDER_CREATED,
            )
        else:
            create_notification(
                user=instance.user,
                title='سفارش ثبت شد',
                message=f'سفارش {instance.order_number} با موفقیت ثبت شد.',
                notification_type=Notification.TYPE_ORDER_CREATED,
            )
        return

    previous = getattr(instance, '_previous_status', None)
    if not previous or previous == instance.status:
        return

    num = instance.order_number

    # Status-specific notifications with meaningful messages.
    # Recovery (reopen) transitions are checked BEFORE the regular branches
    # so they get a distinct notification type and message.
    if instance.status == Order.STATUS_IN_PROGRESS and previous == Order.STATUS_COMPLETED:
        create_notification(
            user=instance.user,
            title='سفارش مجدداً فعال شد 🔄',
            message=(
                f'سفارش {num} که قبلاً تکمیل‌شده بود، مجدداً بازگشایی شد '
                f'و به مرحله در حال انجام بازگشت.'
            ),
            notification_type=Notification.TYPE_ORDER_REOPENED,
        )
    elif instance.status == Order.STATUS_UNDER_REVIEW and previous == Order.STATUS_CANCELLED:
        create_notification(
            user=instance.user,
            title='سفارش برای بررسی مجدد بازگشایی شد 🔄',
            message=(
                f'سفارش {num} که قبلاً لغو شده بود، مجدداً بازگشایی شد '
                f'و برای ادامه بررسی فعال است.'
            ),
            notification_type=Notification.TYPE_ORDER_REACTIVATED,
        )
    elif instance.status == Order.STATUS_UNDER_REVIEW:
        create_notification(
            user=instance.user,
            title='سفارش در حال بررسی است',
            message=f'سفارش {num} وارد مرحله بررسی شد. به زودی با شما تماس خواهیم گرفت.',
            notification_type=Notification.TYPE_ORDER_IN_REVIEW,
        )
    elif instance.status == Order.STATUS_IN_PROGRESS:
        create_notification(
            user=instance.user,
            title='سفارش در حال انجام است',
            message=f'سفارش {num} وارد مرحله انجام شد. تیم جت‌پی‌۲۴ مشغول پردازش است.',
            notification_type=Notification.TYPE_ORDER_IN_PROGRESS,
        )
    elif instance.status == Order.STATUS_WAITING_CUSTOMER:
        create_notification(
            user=instance.user,
            title='⚠️ سفارش نیاز به اقدام شما دارد',
            message=(
                f'سفارش {num} منتظر پاسخ شما است. '
                'لطفاً به صفحه سفارش مراجعه کنید.'
            ),
            notification_type=Notification.TYPE_ORDER_WAITING_CUSTOMER,
        )
    elif instance.status == Order.STATUS_COMPLETED:
        create_notification(
            user=instance.user,
            title='سفارش تکمیل شد ✅',
            message=f'سفارش {num} با موفقیت تکمیل شد. از اعتماد شما سپاسگزاریم.',
            notification_type=Notification.TYPE_ORDER_COMPLETED,
        )
    elif instance.status == Order.STATUS_CANCELLED:
        create_notification(
            user=instance.user,
            title='سفارش لغو شد',
            message=f'سفارش {num} لغو شد. در صورت سؤال با پشتیبانی تماس بگیرید.',
            notification_type=Notification.TYPE_ORDER_CANCELLED,
        )
    else:
        # Generic fallback for any other status change
        create_notification(
            user=instance.user,
            title='وضعیت سفارش تغییر کرد',
            message=(
                f'وضعیت سفارش {num} '
                f'به «{instance.status_label}» تغییر یافت.'
            ),
            notification_type=Notification.TYPE_ORDER_STATUS_CHANGED,
        )


@receiver(post_save, sender=OrderMessage)
def _notify_admin_message(sender, instance, created, **kwargs):
    if not created:
        return
    if not instance.sender or not instance.sender.is_staff:
        return
    preview = instance.message.strip()
    if len(preview) > 120:
        preview = preview[:117] + '…'
    create_notification(
        user=instance.order.user,
        title='پیام جدید از تیم جت‌پی‌۲۴',
        message=preview or 'پیام جدیدی برای سفارش شما ثبت شد.',
        notification_type=Notification.TYPE_ADMIN_MESSAGE,
    )


@receiver(pre_save, sender=KYCProfile)
def _cache_kyc_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._previous_status = (
                KYCProfile.objects.filter(pk=instance.pk)
                .values_list('status', flat=True)
                .first()
            )
        except KYCProfile.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(post_save, sender=KYCProfile)
def _notify_kyc_status(sender, instance, created, **kwargs):
    if created:
        return

    previous = getattr(instance, '_previous_status', None)
    if previous == instance.status:
        return

    if instance.status == KYCProfile.STATUS_APPROVED:
        create_notification(
            user=instance.user,
            title='احراز هویت تأیید شد',
            message='احراز هویت شما توسط تیم جت‌پی‌۲۴ تأیید شد.',
            notification_type=Notification.TYPE_KYC_APPROVED,
        )
    elif instance.status == KYCProfile.STATUS_REJECTED:
        create_notification(
            user=instance.user,
            title='احراز هویت رد شد',
            message='احراز هویت شما رد شد. لطفاً مدارک را بررسی و مجدداً ارسال کنید.',
            notification_type=Notification.TYPE_KYC_REJECTED,
        )
    elif instance.status == KYCProfile.STATUS_NEEDS_CORRECTION:
        note = instance.admin_note.strip() if instance.admin_note else ''
        message = (
            f'مدارک احراز هویت شما نیاز به اصلاح دارد. {note}'
            if note
            else 'مدارک احراز هویت شما نیاز به اصلاح دارد. لطفاً مدارک را بررسی و ارسال کنید.'
        )
        create_notification(
            user=instance.user,
            title='مدارک نیاز به اصلاح دارند',
            message=message,
            notification_type=Notification.TYPE_KYC_NEEDS_CORRECTION,
        )

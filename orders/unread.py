"""Unread admin-message helpers for customer-facing views."""

from django.db.models import Count, Q

from .models import Order, OrderMessage

UNREAD_STAFF_MESSAGE_Q = Q(is_read=False, sender__is_staff=True)

UNREAD_STAFF_MESSAGE_RELATED_Q = Q(
    messages__is_read=False,
    messages__sender__is_staff=True,
)


def count_unread_messages(user):
    """Total unread staff messages across all of the user's orders."""
    return OrderMessage.objects.filter(
        order__user=user,
    ).filter(UNREAD_STAFF_MESSAGE_Q).count()


def mark_order_admin_messages_read(order):
    """Mark all staff messages on an order as read."""
    return order.messages.filter(
        is_read=False,
        sender__is_staff=True,
    ).update(is_read=True)


def orders_with_unread_counts(user):
    """Return the user's orders annotated with unread_count."""
    return (
        Order.objects
        .filter(user=user)
        .annotate(
            unread_count=Count(
                'messages',
                filter=UNREAD_STAFF_MESSAGE_RELATED_Q,
            ),
        )
    )

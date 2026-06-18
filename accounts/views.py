from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django_ratelimit.decorators import ratelimit

from kyc.models import KYCProfile
from orders.models import Order, OrderMessage
from orders.unread import count_unread_messages
from .forms import LoginForm, RegistrationForm
from .models import User


@ratelimit(key='ip', rate='5/h', method='POST', block=True, group='register')
def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            User.objects.create_user(
                email=data['email'],
                password=data['password1'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                phone=data.get('phone'),
            )
            return redirect(settings.LOGIN_URL)
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {
        'form': form,
        'login_url': settings.LOGIN_URL,
    })


@ratelimit(key='ip', rate='5/5m', method='POST', block=True, group='login')
def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = LoginForm(request)

    return render(request, 'accounts/login.html', {
        'form': form,
        'register_url': '/register/',
    })


def logout_view(request):
    logout(request)
    return redirect('/')


def _build_dashboard_notifications(kyc_profile, order_stats, user):
    """
    Build up to 5 dashboard notifications from existing KYC/order data.
    Sorted by fixed importance priority, then recency within the same tier.
    """
    notifications = []
    user_orders = Order.objects.filter(user=user)

    kyc_sort_key = (
        kyc_profile.updated_at.timestamp()
        if kyc_profile else user.date_joined.timestamp()
    )

    if kyc_profile and kyc_profile.status == KYCProfile.STATUS_REJECTED:
        notifications.append({
            'type': 'danger',
            'icon': 'bi-exclamation-triangle-fill',
            'emoji': '⚠️',
            'message': 'احراز هویت شما نیازمند اصلاح است.',
            'priority': 100,
            'sort_key': kyc_sort_key,
        })
    elif kyc_profile and kyc_profile.status == KYCProfile.STATUS_PENDING:
        notifications.append({
            'type': 'warning',
            'icon': 'bi-hourglass-split',
            'emoji': '⏳',
            'message': 'احراز هویت شما در حال بررسی است.',
            'priority': 90,
            'sort_key': kyc_sort_key,
        })
    elif not kyc_profile or kyc_profile.status == KYCProfile.STATUS_NOT_SUBMITTED:
        notifications.append({
            'type': 'warning',
            'icon': 'bi-pencil-square',
            'emoji': '📝',
            'message': 'لطفاً احراز هویت خود را تکمیل کنید.',
            'priority': 85,
            'sort_key': kyc_sort_key,
        })

    unread_count = count_unread_messages(user)
    if unread_count > 0:
        latest_unread = (
            OrderMessage.objects.filter(
                order__user=user,
                is_read=False,
                sender__is_staff=True,
            )
            .order_by('-created_at')
            .first()
        )
        notifications.append({
            'type': 'primary',
            'icon': 'bi-envelope-fill',
            'emoji': '📨',
            'message': f'شما {unread_count} پیام خوانده‌نشده دارید.',
            'priority': 88,
            'sort_key': latest_unread.created_at.timestamp() if latest_unread else 0,
        })

    pending_count = order_stats['pending_orders']
    if pending_count > 0:
        latest_pending = (
            user_orders
            .filter(status__in=[Order.STATUS_SUBMITTED, Order.STATUS_UNDER_REVIEW])
            .order_by('-created_at')
            .first()
        )
        notifications.append({
            'type': 'info',
            'icon': 'bi-search',
            'emoji': '🔍',
            'message': f'شما {pending_count} سفارش در انتظار بررسی دارید.',
            'priority': 80,
            'sort_key': latest_pending.created_at.timestamp() if latest_pending else 0,
        })

    in_progress_count = order_stats['in_progress_orders']
    if in_progress_count > 0:
        latest_in_progress = (
            user_orders
            .filter(status=Order.STATUS_IN_PROGRESS)
            .order_by('-updated_at')
            .first()
        )
        notifications.append({
            'type': 'primary',
            'icon': 'bi-rocket-takeoff-fill',
            'emoji': '🚀',
            'message': f'شما {in_progress_count} سفارش در حال انجام دارید.',
            'priority': 70,
            'sort_key': latest_in_progress.updated_at.timestamp() if latest_in_progress else 0,
        })

    total_orders = order_stats['total_orders']
    if total_orders > 0:
        latest_order = user_orders.order_by('-created_at').first()
        notifications.append({
            'type': 'neutral',
            'icon': 'bi-box-seam-fill',
            'emoji': '📦',
            'message': f'شما تاکنون {total_orders} سفارش ثبت کرده‌اید.',
            'priority': 60,
            'sort_key': latest_order.created_at.timestamp() if latest_order else 0,
        })

    completed_count = order_stats['completed_orders']
    if completed_count > 0:
        latest_completed = (
            user_orders
            .filter(status=Order.STATUS_COMPLETED)
            .order_by('-updated_at')
            .first()
        )
        notifications.append({
            'type': 'success',
            'icon': 'bi-check-circle-fill',
            'emoji': '✅',
            'message': f'تاکنون {completed_count} سفارش شما با موفقیت تکمیل شده است.',
            'priority': 50,
            'sort_key': latest_completed.updated_at.timestamp() if latest_completed else 0,
        })

    if kyc_profile and kyc_profile.status == KYCProfile.STATUS_APPROVED:
        notifications.append({
            'type': 'success',
            'icon': 'bi-shield-check',
            'emoji': '✅',
            'message': 'احراز هویت شما تأیید شده است.',
            'priority': 40,
            'sort_key': kyc_sort_key,
        })

    notifications.sort(key=lambda item: (-item['priority'], -item['sort_key']))
    return notifications[:5]


@login_required
def dashboard(request):
    try:
        kyc_profile = request.user.kyc_profile
    except KYCProfile.DoesNotExist:
        kyc_profile = None

    order_stats = Order.objects.filter(user=request.user).aggregate(
        total_orders=Count('id'),
        pending_orders=Count(
            'id',
            filter=Q(status__in=[Order.STATUS_SUBMITTED, Order.STATUS_UNDER_REVIEW]),
        ),
        in_progress_orders=Count('id', filter=Q(status=Order.STATUS_IN_PROGRESS)),
        completed_orders=Count('id', filter=Q(status=Order.STATUS_COMPLETED)),
    )

    recent_orders = (
        Order.objects.filter(user=request.user)
        .select_related('category', 'subcategory')
        .order_by('-created_at')[:5]
    )

    notifications = _build_dashboard_notifications(
        kyc_profile, order_stats, request.user,
    )

    return render(request, 'accounts/dashboard.html', {
        'kyc_profile': kyc_profile,
        'recent_orders': recent_orders,
        'notifications': notifications,
        **order_stats,
    })

from django.shortcuts import redirect, render

from .forms import OrderForm
from .models import Order


def order_create(request):
    if request.method == 'POST':
        form = OrderForm(request.POST, request.FILES)
        if form.is_valid():
            order = form.save()
            return redirect('order_success', tracking_code=order.tracking_code)
    else:
        form = OrderForm()

    return render(request, 'orders/order_create.html', {'form': form})


def order_success(request, tracking_code):
    return render(request, 'orders/order_success.html', {
        'tracking_code': tracking_code,
    })


def order_tracking(request):
    order = None
    error = None
    query = request.GET.get('code', '').strip().upper()

    if query:
        try:
            order = Order.objects.get(tracking_code=query)
        except Order.DoesNotExist:
            error = 'کد پیگیری یافت نشد. لطفاً کد را دوباره بررسی کنید.'

    return render(request, 'orders/order_tracking.html', {
        'order': order,
        'error': error,
        'query': query,
    })

"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from orders.views import order_tracking

admin.site.site_header = 'جت‌پی‌۲۴ — پنل مدیریت'
admin.site.site_title = 'JetPay24 Admin'
admin.site.index_title = 'مدیریت سایت'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pages.urls')),
    path('', include('accounts.urls')),
    path('dashboard/kyc/', include('kyc.urls')),
    path('dashboard/orders/', include('orders.urls')),
    path('dashboard/notifications/', include('notifications.urls')),
    path('dashboard/payments/', include('payments.urls')),
    path('dashboard/services/', include('services.urls')),
    path('tracking/', order_tracking, name='order_tracking'),
]

if settings.DEBUG:
    # Serve PUBLIC media only (KYC images, avatars, guide images, etc.).
    # Order attachment files are stored at PRIVATE_MEDIA_ROOT — a separate
    # directory that is NOT MEDIA_ROOT — so they are never included here.
    # In production, your web server must also have NO rule for PRIVATE_MEDIA_ROOT.
    # All order file access goes through authenticated download views only.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

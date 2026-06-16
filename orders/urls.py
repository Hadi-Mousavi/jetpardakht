from django.urls import path

from . import views

urlpatterns = [
    path('', views.order_create, name='order_create'),
    path('success/<str:tracking_code>/', views.order_success, name='order_success'),
]

from django.urls import path

from . import otp_views
from .views import dashboard, login_view, logout_view, register

urlpatterns = [
    path('register/', register, name='register'),
    path('auth/login/', login_view, name='login'),
    path('auth/logout/', logout_view, name='logout'),
    path('auth/otp/request/', otp_views.otp_request, name='otp_request'),
    path('auth/otp/resend/', otp_views.otp_resend, name='otp_resend'),
    path('dashboard/', dashboard, name='dashboard'),
]

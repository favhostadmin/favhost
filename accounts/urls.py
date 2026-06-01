from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import (
    CustomLoginView,
    profile_view,
    register_view,
    verify_otp_view,
    resend_otp_view,
    forgot_password_view,
    forgot_resend_otp_view,
)

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', profile_view, name='profile'),

    # Signup / OTP
    path('register/', register_view, name='register'),
    path('verify-otp/', verify_otp_view, name='verify_otp'),
    path('resend-otp/', resend_otp_view, name='resend_otp'),

    # Forgot Password
    path('forgot-password/', forgot_password_view, name='forgot_password'),
    path('forgot-resend-otp/', forgot_resend_otp_view, name='forgot_resend_otp'),
]

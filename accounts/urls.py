from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import (
    CustomLoginView,
    profile_view,
    profile_edit_view,
    register_view,
    verify_otp_view,
    resend_otp_view,
    forgot_password_view,
    forgot_resend_otp_view,
    delete_document_view,
    update_social_url,
    manage_cohost_view,
    firebase_auth_view,
)

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('firebase-auth/', firebase_auth_view, name='firebase_auth'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', profile_view, name='profile'),
    path('profile/edit/', profile_edit_view, name='profile_edit'),
    path('profile/document/delete/<int:doc_id>/', delete_document_view, name='delete_document'),

    # Signup / OTP
    path('register/', register_view, name='register'),
    path('verify-otp/', verify_otp_view, name='verify_otp'),
    path('resend-otp/', resend_otp_view, name='resend_otp'),

    # Forgot Password
    path('forgot-password/', forgot_password_view, name='forgot_password'),
    path('forgot-resend-otp/', forgot_resend_otp_view, name='forgot_resend_otp'),
    path('profile/update-social/', update_social_url, name='update_social_url'),

    # Co-host Management
    path('profile/manage-co-host/', manage_cohost_view, name='manage_cohost'),
    path('profile/manage-co-host/<int:cohost_id>/', manage_cohost_view, name='manage_cohost_detail'),
]


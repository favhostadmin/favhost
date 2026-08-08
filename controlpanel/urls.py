from django.urls import path

from . import views

app_name = 'controlpanel'

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('no-access/', views.no_access, name='no_access'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Users / hosts
    path('users/', views.users_list, name='users'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/action/', views.user_action, name='user_action'),

    # Properties
    path('properties/', views.properties_list, name='properties'),
    path('properties/<uuid:pk>/', views.property_detail, name='property_detail'),

    # Bookings
    path('bookings/', views.bookings_list, name='bookings'),
    path('bookings/<uuid:pk>/', views.booking_detail, name='booking_detail'),

    # Enquiries
    path('enquiries/', views.enquiries_list, name='enquiries'),

    # Subscriptions & finance
    path('subscriptions/', views.subscriptions_list, name='subscriptions'),
    path('payments/', views.payments_list, name='payments'),

    # Platform settings & console delegates
    path('settings/', views.platform_settings, name='settings'),
    path('co-admins/', views.co_admins, name='co_admins'),
]

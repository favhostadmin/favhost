from django.urls import path
from . import views

urlpatterns = [
    # Pricing / upgrade page (shown when user clicks Upgrade on profile)
    path('upgrade/', views.pricing_page, name='pricing'),

    # Stripe Checkout: creates session and redirects to Stripe
    path('create-checkout-session/', views.create_checkout_session,
         name='create_checkout_session'),

    # Stripe redirects back here after payment
    path('checkout/success/', views.checkout_success, name='checkout_success'),
    path('checkout/cancel/', views.checkout_cancel, name='checkout_cancel'),

    # Stripe Customer Portal: let user manage/cancel subscription
    path('billing/portal/', views.customer_portal, name='customer_portal'),

    # Stripe webhooks: events sent from Stripe to your server
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),

    # Subscription detail + transaction history
    path('subscription/', views.subscription_detail, name='subscription'),
]

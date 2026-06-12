from django.contrib import admin
from .models import StripeCustomer


@admin.register(StripeCustomer)
class StripeCustomerAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'stripe_customer_id', 'stripe_subscription_id',
        'subscription_status', 'current_period_end', 'updated_at'
    ]
    list_filter = ['subscription_status']
    search_fields = ['user__username', 'user__email', 'stripe_customer_id']
    readonly_fields = ['created_at', 'updated_at']

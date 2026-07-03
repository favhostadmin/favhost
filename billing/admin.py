from django.contrib import admin
from .models import StripeCustomer, PlatformSetting


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    """Single, always-present row of site-wide pricing & trial settings."""
    list_display = ['__str__', 'subscription_price', 'subscription_currency',
                    'subscription_interval', 'free_trial_days', 'updated_at']
    readonly_fields = ['updated_at']
    fieldsets = (
        ('Subscription price (display only — also update Stripe)', {
            'fields': ('subscription_price', 'subscription_currency', 'subscription_interval'),
        }),
        ('Free trial', {
            'fields': ('free_trial_days',),
            'description': "Applies to NEW signups only; existing accounts keep their original trial length.",
        }),
        (None, {'fields': ('updated_at',)}),
    )

    def has_add_permission(self, request):
        # Only ever one settings row; edit the existing one.
        return not PlatformSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Ensure the singleton row exists so it's always there to edit.
        PlatformSetting.load()
        return super().changelist_view(request, extra_context)


@admin.register(StripeCustomer)
class StripeCustomerAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'stripe_customer_id', 'stripe_subscription_id',
        'subscription_status', 'current_period_end', 'updated_at'
    ]
    list_filter = ['subscription_status']
    search_fields = ['user__username', 'user__email', 'stripe_customer_id']
    readonly_fields = ['created_at', 'updated_at']

from django import forms
from django.contrib import admin
from .models import StripeCustomer, PlatformSetting


class PlatformSettingAdminForm(forms.ModelForm):
    """Validates Stripe price IDs against the Stripe API at form-clean time.

    Doing this in clean() (rather than letting model.save() raise) means a
    bad/archived price ID becomes a normal, in-place form error — not a 500
    page, and not a misleading "changed successfully" message after a save
    that was actually rejected.
    """
    class Meta:
        model = PlatformSetting
        fields = '__all__'

    def _validate(self, field_name, price_id):
        if not price_id or price_id == getattr(self.instance, field_name):
            return
        from .models import fetch_stripe_price_details
        try:
            fetch_stripe_price_details(price_id)
        except Exception as e:
            raise forms.ValidationError(str(e))

    def clean_stripe_price_id_monthly(self):
        value = self.cleaned_data['stripe_price_id_monthly']
        self._validate('stripe_price_id_monthly', value)
        return value

    def clean_stripe_price_id_yearly(self):
        value = self.cleaned_data['stripe_price_id_yearly']
        self._validate('stripe_price_id_yearly', value)
        return value


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    """Single, always-present row of site-wide pricing & trial settings."""
    form = PlatformSettingAdminForm
    list_display = ['__str__', 'stripe_price_id_monthly', 'subscription_price', 'subscription_price_yearly',
                    'subscription_currency', 'free_trial_days', 'updated_at']
    readonly_fields = ['subscription_price', 'subscription_interval', 'subscription_price_yearly',
                       'subscription_interval_yearly', 'subscription_currency', 'updated_at']
    fieldsets = (
        ('Stripe price IDs (this is what actually gets charged)', {
            'fields': ('stripe_price_id_monthly', 'stripe_price_id_yearly'),
            'description': "Create the price in the Stripe dashboard first, then paste its ID "
                           "here. Amount, currency and interval below are fetched from Stripe "
                           "automatically on save — they are not editable directly, so the "
                           "displayed price can never drift from what Stripe actually bills.",
        }),
        ('Fetched from Stripe (read-only)', {
            'fields': ('subscription_price', 'subscription_interval',
                      'subscription_price_yearly', 'subscription_interval_yearly',
                      'subscription_currency'),
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

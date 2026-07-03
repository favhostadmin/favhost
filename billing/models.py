from django.db import models
from django.conf import settings


class PlatformSetting(models.Model):
    """Site-wide, admin-editable settings for pricing and the free trial.

    This is a singleton (always exactly one row, pk=1). Edit it from the admin
    panel to change the price shown across the platform and the free-trial
    length applied to NEW signups. Existing accounts are unaffected: each user's
    trial length is captured on their record at signup (see MyUser.trial_days),
    and changing the price here only affects what is displayed — actual Stripe
    billing must still be updated in the Stripe dashboard.
    """
    subscription_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=9.99,
        help_text="Monthly price shown across the platform (display only — "
                  "update Stripe separately for real billing).",
    )
    subscription_currency = models.CharField(
        max_length=10, default='USD',
        help_text="3-letter currency code, e.g. USD, EUR, GBP.",
    )
    subscription_interval = models.CharField(
        max_length=20, default='month',
        help_text="Billing interval label, e.g. month or year.",
    )
    free_trial_days = models.PositiveIntegerField(
        default=90,
        help_text="Free-trial length for NEW accounts (in days). Changing this "
                  "does not affect accounts that already signed up.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Setting'
        verbose_name_plural = 'Platform Settings'

    def __str__(self):
        return f"Platform settings (price {self.amount_display}/{self.subscription_interval}, trial {self.free_trial_days}d)"

    def save(self, *args, **kwargs):
        # Enforce the singleton: there is only ever one row, pk=1.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Never delete the singleton.
        pass

    @classmethod
    def load(cls):
        """Return the single settings row, creating it with defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def amount_display(self):
        """e.g. '$9.99' — currency-formatted amount without the interval."""
        from .emails import format_price
        return format_price(self.subscription_price, self.subscription_currency)

    @property
    def full_display(self):
        """e.g. '$9.99/month' — amount plus interval."""
        return f"{self.amount_display}/{self.subscription_interval}"


class StripeCustomer(models.Model):
    """
    Links a FavHost user to their Stripe records.

    What is deliberately NOT here:
    - No card number
    - No expiry date
    - No CVC
    Card data lives ONLY inside Stripe. We store only identifiers.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stripe_customer'
    )
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    subscription_status = models.CharField(
        max_length=50,
        blank=True,
        help_text="active, past_due, canceled, or empty"
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    # Set True after the one-time "subscription confirmed" email is sent,
    # so the user only ever receives it on their very first subscription.
    confirmation_email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self):
        return self.subscription_status == 'active'

    def __str__(self):
        return f"{self.user.username} — {self.subscription_status or 'no subscription'}"

    class Meta:
        verbose_name = 'Stripe Customer'
        verbose_name_plural = 'Stripe Customers'

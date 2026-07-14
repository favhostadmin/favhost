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
    subscription_price_yearly = models.DecimalField(
        max_digits=8, decimal_places=2, default=99.99,
        help_text="Yearly price shown across the platform (display only — "
                  "update Stripe separately for real billing).",
    )
    subscription_interval_yearly = models.CharField(
        max_length=20, default='year',
        help_text="Yearly billing interval label, e.g. year.",
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

    @property
    def interval_adverb(self):
        """Turn the interval into an adverb for copy, e.g. 'month' -> 'monthly'.

        Robust to admin entering either the noun ('month') or the adverb
        ('Monthly') — avoids bugs like 'Daily' -> 'Dailyly'.
        """
        key = (self.subscription_interval or 'month').strip().lower()
        mapping = {
            'day': 'daily', 'week': 'weekly', 'month': 'monthly', 'year': 'yearly',
            'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly', 'yearly': 'yearly',
        }
        if key in mapping:
            return mapping[key]
        return key if key.endswith('ly') else f"{key}ly"

    # ── Yearly plan display helpers (mirror the monthly ones) ─────────────
    @property
    def amount_display_yearly(self):
        """e.g. '$99.99' — yearly amount without the interval."""
        from .emails import format_price
        return format_price(self.subscription_price_yearly, self.subscription_currency)

    @property
    def full_display_yearly(self):
        """e.g. '$99.99/year' — yearly amount plus interval."""
        return f"{self.amount_display_yearly}/{self.subscription_interval_yearly}"

    @property
    def yearly_monthly_equivalent_display(self):
        """e.g. '$8.33' — the yearly price broken down per month (display only)."""
        from .emails import format_price
        monthly = (self.subscription_price_yearly or 0) / 12
        return format_price(monthly, self.subscription_currency)

    @property
    def yearly_anchor_display(self):
        """A year's cost at the MONTHLY rate (monthly x 12), e.g. '$119.88'.

        Shown struck-through next to the yearly price to anchor the saving.
        """
        from .emails import format_price
        return format_price((self.subscription_price or 0) * 12, self.subscription_currency)

    @property
    def yearly_savings_percent(self):
        """Percent saved by paying yearly vs 12x the monthly price, e.g. 17."""
        try:
            monthly_annual = float(self.subscription_price) * 12
            yearly = float(self.subscription_price_yearly)
            if monthly_annual <= 0:
                return 0
            return round((monthly_annual - yearly) / monthly_annual * 100)
        except (TypeError, ValueError):
            return 0


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

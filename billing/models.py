from decimal import Decimal

from django.db import models
from django.conf import settings


def fetch_stripe_price_details(price_id):
    """Fetch `price_id` from Stripe and return (amount, currency, interval).

    amount is a Decimal in major units (e.g. 9.99), currency is upper-cased
    (e.g. 'USD'), interval is Stripe's recurring interval (e.g. 'month').

    Raises ValueError for a price that exists but isn't usable here (archived,
    no fixed amount, not recurring), or stripe.error.StripeError for anything
    Stripe itself rejects (unknown ID, wrong API key/mode, network failure).
    """
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    price = stripe.Price.retrieve(price_id)

    # stripe-python's Price is a typed object, not a dict — no .get() here.
    if not getattr(price, 'active', True):
        raise ValueError(f"Stripe price {price_id} is archived/inactive in Stripe.")
    if getattr(price, 'unit_amount', None) is None:
        raise ValueError(
            f"Stripe price {price_id} has no fixed unit amount (metered or "
            f"tiered prices aren't supported here)."
        )
    recurring = getattr(price, 'recurring', None)
    if not recurring:
        raise ValueError(f"Stripe price {price_id} is not a recurring price.")

    amount = Decimal(price.unit_amount) / Decimal(100)
    currency = (getattr(price, 'currency', None) or 'usd').upper()
    interval = getattr(recurring, 'interval', None) or 'month'
    return amount, currency, interval


class PlatformSetting(models.Model):
    """Site-wide, admin-editable settings for pricing and the free trial.

    This is a singleton (always exactly one row, pk=1). Edit it from the admin
    panel (or the owner console) to change the plan Stripe actually charges,
    and the free-trial length applied to NEW signups.

    Stripe price IDs (``stripe_price_id_monthly`` / ``stripe_price_id_yearly``)
    are the single source of truth: they are not secrets (Stripe.js exposes
    them client-side on Checkout anyway), they change far more often than a
    deploy cycle, and they're business config — so they live here in the DB
    instead of an env var / AWS Secrets Manager entry that needs a manual
    EC2 + gunicorn restart every time the price changes.

    The display fields (``subscription_price`` etc.) are NOT independently
    editable — they are a cache, populated automatically from Stripe by
    ``save()`` whenever a price ID changes. This keeps the UI-shown amount and
    what Stripe actually bills structurally impossible to drift apart, which
    is what used to happen when both were typed in by hand separately.
    """
    stripe_price_id_monthly = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Stripe Price ID for the monthly plan (e.g. price_1AbC...). "
                  "This is what Stripe actually charges. Create it in the "
                  "Stripe dashboard first, then paste it here — the amount, "
                  "currency and interval below are fetched from Stripe "
                  "automatically.",
    )
    stripe_price_id_yearly = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Stripe Price ID for the yearly plan. Same rules as the "
                  "monthly price ID above.",
    )
    subscription_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=9.99,
        help_text="Monthly price shown across the platform. Auto-filled from "
                  "the Stripe price ID above — do not edit directly.",
    )
    subscription_currency = models.CharField(
        max_length=10, default='USD',
        help_text="3-letter currency code, e.g. USD, EUR, GBP. Auto-filled "
                  "from Stripe.",
    )
    subscription_interval = models.CharField(
        max_length=20, default='month',
        help_text="Billing interval label, e.g. month or year. Auto-filled "
                  "from Stripe.",
    )
    subscription_price_yearly = models.DecimalField(
        max_digits=8, decimal_places=2, default=99.99,
        help_text="Yearly price shown across the platform. Auto-filled from "
                  "the Stripe price ID above — do not edit directly.",
    )
    subscription_interval_yearly = models.CharField(
        max_length=20, default='year',
        help_text="Yearly billing interval label, e.g. year. Auto-filled "
                  "from Stripe.",
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

        # Whenever a Stripe price ID changed, re-fetch its amount/currency/
        # interval from Stripe so the display cache can never drift from what
        # Stripe actually bills. Comparison is against the DB, not against
        # `self`, so this only fires on an actual change — not on every save
        # (e.g. just editing free_trial_days).
        old = PlatformSetting.objects.filter(pk=1).first() if not self._state.adding else None
        if self.stripe_price_id_monthly and self.stripe_price_id_monthly != (old.stripe_price_id_monthly if old else ''):
            self._sync_stripe_price('monthly', self.stripe_price_id_monthly)
        if self.stripe_price_id_yearly and self.stripe_price_id_yearly != (old.stripe_price_id_yearly if old else ''):
            self._sync_stripe_price('yearly', self.stripe_price_id_yearly)

        super().save(*args, **kwargs)

    def _sync_stripe_price(self, which, price_id):
        """Fetch `price_id` from Stripe and populate the matching display
        fields from it. Raises ValueError (bad/unsupported price) or
        stripe.error.StripeError (network/API/auth problem, unknown ID) —
        callers must catch these and must NOT save a half-applied form on
        failure, so the display cache never shows an amount Stripe didn't
        confirm.
        """
        amount, currency, interval = fetch_stripe_price_details(price_id)

        # Both plans share one currency field on this model — keep it in
        # sync with whichever price was just fetched.
        self.subscription_currency = currency
        if which == 'yearly':
            self.subscription_price_yearly = amount
            self.subscription_interval_yearly = interval
        else:
            self.subscription_price = amount
            self.subscription_interval = interval

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

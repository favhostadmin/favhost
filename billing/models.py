from django.db import models
from django.conf import settings


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

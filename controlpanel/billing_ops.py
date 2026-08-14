"""Owner-initiated subscription changes, executed against Stripe first.

Why this lives behind a helper rather than inline in the view: every one of
these actions moves real money, and the ordering matters. Stripe is the system
of record for billing — our ``StripeCustomer`` row is a mirror of it. So the
remote call happens FIRST and the local row is only updated once Stripe has
confirmed. The reverse order is the dangerous one: marking a subscription
cancelled locally while Stripe keeps charging the card produces exactly the
outcome the console is meant to prevent — a host who sees "cancelled" and is
still billed next month.

If Stripe refuses, nothing is written locally and the caller surfaces the
error. A half-applied cancellation is worse than a failed one.
"""
import logging

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)

stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''


def _has_remote(sc):
    return bool(sc and sc.stripe_subscription_id)


def cancel_now(sc):
    """End the subscription immediately — billing stops from this moment.

    Returns ``(ok, message)``. A record with no Stripe subscription id (comped
    or legacy) is cancellable locally: there is nothing remote to stop, so
    refusing would leave the owner unable to tidy up their own data.
    """
    if not _has_remote(sc):
        return True, 'No Stripe subscription on file — cleared locally only.'
    try:
        stripe.Subscription.delete(sc.stripe_subscription_id)
        return True, ''
    except Exception as exc:
        logger.warning('Stripe immediate-cancel failed for %s: %s', sc.stripe_subscription_id, exc)
        return False, str(exc)


def cancel_at_period_end(sc):
    """Stop the next renewal but let the paid-for period run out.

    The fairer option when someone has already paid for the current month:
    they keep what they bought, and no further charge is taken.
    """
    if not _has_remote(sc):
        return False, 'This account has no Stripe subscription to schedule.'
    try:
        stripe.Subscription.modify(sc.stripe_subscription_id, cancel_at_period_end=True)
        return True, ''
    except Exception as exc:
        logger.warning('Stripe cancel-at-period-end failed for %s: %s', sc.stripe_subscription_id, exc)
        return False, str(exc)


def resume(sc):
    """Undo a scheduled cancellation, so the subscription renews as normal."""
    if not _has_remote(sc):
        return False, 'This account has no Stripe subscription to resume.'
    try:
        stripe.Subscription.modify(sc.stripe_subscription_id, cancel_at_period_end=False)
        return True, ''
    except Exception as exc:
        logger.warning('Stripe resume failed for %s: %s', sc.stripe_subscription_id, exc)
        return False, str(exc)

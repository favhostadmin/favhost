from datetime import timedelta
from django.utils import timezone

from .models import PlatformSetting


def _platform_price_context(settings_obj):
    """Admin-editable pricing/trial values, exposed on every page."""
    return {
        'platform_price': settings_obj.amount_display,           # e.g. "$9.99"
        'platform_price_amount': settings_obj.subscription_price,  # e.g. 9.99 (raw)
        'platform_price_interval': settings_obj.subscription_interval,
        'platform_price_interval_adverb': settings_obj.interval_adverb,  # e.g. "monthly"
        'platform_price_currency': settings_obj.subscription_currency,
        'platform_price_display': settings_obj.full_display,      # e.g. "$9.99/month"
        'platform_trial_days': settings_obj.free_trial_days,
        # Yearly plan (mirrors the monthly values above)
        'platform_price_yearly': settings_obj.amount_display_yearly,       # e.g. "$99.99"
        'platform_price_yearly_amount': settings_obj.subscription_price_yearly,  # raw
        'platform_price_yearly_interval': settings_obj.subscription_interval_yearly,
        'platform_price_yearly_display': settings_obj.full_display_yearly,  # "$99.99/year"
        'platform_price_yearly_per_month': settings_obj.yearly_monthly_equivalent_display,  # "$8.33"
        'platform_price_yearly_was': settings_obj.yearly_anchor_display,  # "$119.88" (monthly x12)
        'platform_price_yearly_savings': settings_obj.yearly_savings_percent,  # e.g. 17
    }


def subscription_status(request):
    settings_obj = PlatformSetting.load()

    if not request.user.is_authenticated:
        return {
            'subscription_status': '',
            'is_premium': False,
            'show_subscription_wall': False,
            'wall_reason': '',
            'trial_end': None,
            **_platform_price_context(settings_obj),
        }

    # Resolve the effective owner (if logged in as co-host, use host's subscription)
    from accounts.utils import get_effective_user
    user = get_effective_user(request.user)

    now = timezone.now()
    # Trial length is captured per-account at signup; fall back to the current
    # platform setting for any legacy record without it.
    # `is None`, not `or`: zero is a real, meaningful value here. The console
    # sets trial_days to 0 when the owner cancels a subscription outright, to
    # close any trial the host could otherwise coast on. Treating 0 as "unset"
    # would hand that host a fresh 90-day trial — the exact opposite of the
    # intent — so only a genuinely missing value falls back to the default.
    trial_days = getattr(user, 'trial_days', None)
    if trial_days is None:
        trial_days = settings_obj.free_trial_days
    trial_end = user.created_at + timedelta(days=trial_days)
    trial_expired = now > trial_end

    try:
        sc = user.stripe_customer
        is_premium = sc.is_active
        sub_status = sc.subscription_status
    except Exception:
        is_premium = False
        sub_status = ''

    if user.is_subscription_free:
        is_premium = True

    # Show the paywall only when the user has NO access at all: no active
    # subscription AND their 90-day trial is over. A user who cancels while still
    # inside the trial keeps trial access for the remaining days, so no wall.
    # Skip entirely for users marked as subscription-free (admin toggle).
    show_wall = not is_premium and not user.is_subscription_free and trial_expired

    wall_reason = ''
    if user.is_subscription_free:
        pass
    elif sub_status == 'past_due':
        # A failed/overdue payment locks the platform immediately — unlike
        # a plain trial expiry, this doesn't wait on the trial window at all,
        # since the host already had (and lost) a paid subscription.
        show_wall = True
        wall_reason = 'past_due'
    elif show_wall:
        # Distinguish the message: someone who once subscribed sees "subscription
        # ended"; someone who never subscribed sees "trial expired".
        if sub_status == 'canceled':
            wall_reason = 'canceled'
        else:
            wall_reason = 'trial_expired'

    # When logged in as a co-host, `user` is the host who owns the subscription.
    # Expose their email so the paywall can tell the co-host who to contact
    # (co-hosts can't subscribe themselves).
    is_cohost_viewer = user.pk != request.user.pk
    account_owner_email = user.email if is_cohost_viewer else ''

    return {
        'subscription_status': sub_status,
        'is_premium': is_premium,
        'show_subscription_wall': show_wall,
        'wall_reason': wall_reason,
        'trial_end': trial_end,
        'account_owner_email': account_owner_email,
        # Platform-wide pricing (admin-editable), for display everywhere.
        **_platform_price_context(settings_obj),
    }

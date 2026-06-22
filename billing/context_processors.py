from datetime import timedelta
from django.utils import timezone


def subscription_status(request):
    if not request.user.is_authenticated:
        return {
            'subscription_status': '',
            'is_premium': False,
            'show_subscription_wall': False,
            'wall_reason': '',
            'trial_end': None,
        }

    # Resolve the effective owner (if logged in as co-host, use host's subscription)
    from accounts.utils import get_effective_user
    user = get_effective_user(request.user)

    now = timezone.now()
    trial_end = user.created_at + timedelta(days=90)
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
    if show_wall:
        # Distinguish the message: someone who once subscribed sees "subscription
        # ended"; someone who never subscribed sees "trial expired".
        if sub_status == 'canceled':
            wall_reason = 'canceled'
        else:
            wall_reason = 'trial_expired'

    return {
        'subscription_status': sub_status,
        'is_premium': is_premium,
        'show_subscription_wall': show_wall,
        'wall_reason': wall_reason,
        'trial_end': trial_end,
    }

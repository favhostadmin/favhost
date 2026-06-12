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

    # Show the paywall when the user has no active subscription AND their trial is over
    # or their subscription was explicitly cancelled
    # Skip entirely for users marked as subscription-free (admin toggle)
    show_wall = not is_premium and not user.is_subscription_free and (trial_expired or sub_status == 'canceled')

    wall_reason = ''
    if show_wall:
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

def subscription_status(request):
    if not request.user.is_authenticated:
        return {'subscription_status': '', 'is_premium': False}
    try:
        sc = request.user.stripe_customer
        return {
            'subscription_status': sc.subscription_status,
            'is_premium': sc.is_active,
        }
    except Exception:
        return {'subscription_status': '', 'is_premium': False}

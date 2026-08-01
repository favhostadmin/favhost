"""The host-authored policies shown to guests, and their public URLs.

Kept out of ``views.py`` so ``booking.tasks`` can build policy links for the
check-in email without importing the whole views module.
"""
from django.urls import reverse

#: url kind -> (Property field, guest-facing heading)
PROPERTY_POLICIES = {
    'house-rules': ('house_rules', 'House Rules and Policies'),
    'cancellation-policy': ('cancellation_policy', 'Cancellation Policy'),
    'rental-contract': ('rental_contract_terms', 'Rental Contract Terms and Conditions'),
}


def has_policy(property_obj, kind):
    """Whether the host actually wrote this policy for this listing."""
    field = PROPERTY_POLICIES[kind][0]
    return bool((getattr(property_obj, field, None) or '').strip())


def policy_path(property_obj, kind):
    """Relative URL of a policy page, or '' when the host left it blank.

    Returning '' lets callers hide the link instead of pointing a guest at a
    page that would 404.
    """
    if not has_policy(property_obj, kind):
        return ''
    return reverse('property:property-policy',
                   kwargs={'pk': property_obj.pk, 'kind': kind})

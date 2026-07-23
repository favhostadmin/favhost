from django.conf import settings
from booking.models import Enquiry, Expense
from property.models import Property
from django.db.models import Q
from accounts.utils import get_visible_user_ids, get_effective_user
from accounts.models import CoHost


def google_analytics(request):
    """
    Exposes the GA4 measurement ID to every template so base.html can render
    the tracking snippet site-wide. Only sent when DEBUG is off, so local
    development traffic doesn't get counted in production analytics.
    """
    return {
        "google_analytics_id": settings.GOOGLE_ANALYTICS_ID
    }


def enquiry_counts(request):
    """
    Add enquiry counts and co-host flag to template context for all views.
    `is_cohost` is True when the logged-in user was created as a co-host by
    another host, so templates can hide host-only sections (e.g. Profile page).

    Also exposes the data needed by the header's global "Add Expense" modal
    (`expense_categories`, `expense_listings`) so an expense can be added from
    any page — including for co-hosts, who cannot open the Accounting page.
    """
    if request.user.is_authenticated:
        visible_ids = get_visible_user_ids(request.user)
        new_enquiry_count = Enquiry.objects.filter(
            property__created_by__in=visible_ids,
            is_archive=False,
            is_booked=False,
        ).count()
        is_cohost = CoHost.objects.filter(co_host=request.user).exists()
        return {
            'new_enquiry_count': new_enquiry_count,
            'is_cohost': is_cohost,
            # Effective-user (host) profile completeness — drives the header's
            # "Complete Your Profile" gate on every Create action so co-hosts
            # are gated by the host's profile, matching the server-side checks.
            'header_profile_complete': get_effective_user(request.user).is_profile_complete(),
            'expense_categories': [c[0] for c in Expense.CATEGORY_CHOICES],
            'expense_listings': Property.objects.filter(
                created_by__in=visible_ids
            ).only('id', 'title'),
        }
    return {'new_enquiry_count': 0, 'is_cohost': False}

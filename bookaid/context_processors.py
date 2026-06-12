from booking.models import Enquiry
from django.db.models import Q
from accounts.utils import get_visible_user_ids
from accounts.models import CoHost


def enquiry_counts(request):
    """
    Add enquiry counts and co-host flag to template context for all views.
    `is_cohost` is True when the logged-in user was created as a co-host by
    another host, so templates can hide host-only sections (e.g. Profile page).
    """
    if request.user.is_authenticated:
        new_enquiry_count = Enquiry.objects.filter(
            property__created_by__in=get_visible_user_ids(request.user),
            is_archive=False,
            is_booked=False,
        ).count()
        is_cohost = CoHost.objects.filter(co_host=request.user).exists()
        return {
            'new_enquiry_count': new_enquiry_count,
            'is_cohost': is_cohost,
        }
    return {'new_enquiry_count': 0, 'is_cohost': False}

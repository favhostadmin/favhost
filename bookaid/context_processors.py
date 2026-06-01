from booking.models import Enquiry
from django.db.models import Q

def enquiry_counts(request):
    """
    Add enquiry counts to template context for all views
    """
    if request.user.is_authenticated:
        new_enquiry_count = Enquiry.objects.filter(
            property__created_by=request.user,
            is_archive=False,
            is_booked=False,
        ).count()
        return {
            'new_enquiry_count': new_enquiry_count
        }
    return {'new_enquiry_count': 0}

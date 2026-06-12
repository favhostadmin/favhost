from .models import Property
from accounts.utils import get_visible_user_ids

def property_context(request):
    if request.user.is_authenticated:
        property_count = Property.objects.filter(created_by__in=get_visible_user_ids(request.user)).count()
    else:
        property_count = 0
    return {
        'user_property_count': property_count
    }
from .models import Property

def property_context(request):
    if request.user.is_authenticated:
        property_count = Property.objects.filter(created_by=request.user).count()
    else:
        property_count = 0
    return {
        'user_property_count': property_count
    }
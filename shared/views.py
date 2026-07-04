from django.http import JsonResponse

from .models import CountryAndState


def country_list_api(request):
    """Returns a JSON array of distinct country names."""
    countries = (
        CountryAndState.objects.order_by('country_name')
        .values_list('country_name', flat=True)
        .distinct()
    )
    return JsonResponse(list(countries), safe=False)


def state_list_api(request, country_name):
    """Returns a JSON array of state names for the given country."""
    states = (
        CountryAndState.objects.filter(country_name__iexact=country_name)
        .exclude(state_name__isnull=True)
        .exclude(state_name='')
        .order_by('state_name')
        .values_list('state_name', flat=True)
        .distinct()
    )
    return JsonResponse(list(states), safe=False)

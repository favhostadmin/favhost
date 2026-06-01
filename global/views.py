from django.http import JsonResponse
from .models import Country, State


def country_list_api(request):
    """
    API endpoint to list all countries.
    Returns a JSON array of country objects with 'name' and 'iso2' (country code).
    """
    countries = Country.objects.all().order_by('name')
    data = [{"name": country.name, "iso2": country.code} for country in countries]
    return JsonResponse(data, safe=False)


def state_list_api(request, country_code):
    """
    API endpoint to list states for a given country.
    'country_code' should be the ISO2 code of the country.
    Returns a JSON array of state objects with 'name' and 'iso2' (state code).
    """
    try:
        country = Country.objects.get(code=country_code)
        states = State.objects.filter(country=country).order_by('name')
        data = [{"name": state.name, "iso2": state.code} for state in states]
        return JsonResponse(data, safe=False)
    except Country.DoesNotExist:
        return JsonResponse({"error": "Country not found"}, status=404)
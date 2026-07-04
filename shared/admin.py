from django.contrib import admin

from .models import CountryAndState


@admin.register(CountryAndState)
class CountryAndStateAdmin(admin.ModelAdmin):
    list_display = ('country_name', 'country_code', 'country_short', 'state_name', 'state_code')
    list_filter = ('country_name',)
    search_fields = ('country_name', 'country_code', 'country_short', 'state_name', 'state_code')

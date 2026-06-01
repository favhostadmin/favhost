from django.contrib import admin

# Register your models here.
from .models import Country, State
@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('name', 'short', 'code', 'created_at')
    search_fields = ('name', 'code')

@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'country', 'created_at')
    search_fields = ('name', 'code', 'country__name')

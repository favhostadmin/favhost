from django.contrib import admin
from .models import HousekeepingStatus


@admin.register(HousekeepingStatus)
class HousekeepingStatusAdmin(admin.ModelAdmin):
    list_display = ('property', 'date', 'status', 'updated_at')
    list_filter = ('status', 'date')
    search_fields = ('property__title',)

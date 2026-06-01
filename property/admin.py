from django.contrib import admin
from .models import *
# Register your models here.
# admin.site.register(Amenities)
admin.site.register(Property)
admin.site.register(PropertyImage)
admin.site.register(PropertyDocument)
admin.site.register(PropertyBlockDate)

@admin.register(Amenities)
class AmenitiesAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon')
    search_fields = ('name',)
    ordering = ('name',)

@admin.register(PropertyChannel)
class PropertyChannelAdmin(admin.ModelAdmin):
    list_display = ('property', 'channel_type', 'calendar_link', 'is_connected')
    list_filter = ('channel_type', 'is_connected')
    search_fields = ('property__title', 'channel_type__name')

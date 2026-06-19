from django.contrib import admin
from .models import *
from datetime import date, timedelta
# Register your models here.
admin.site.register(GuestDocument)

@admin.register(BookingChannel)
class BookingChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'color')

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'first_name', 'property', 'check_in_date', 'check_out_date', 'status', 'purpose_of_stay', 'notes', 'last_synced_at', 'created_at')
    list_filter = ('status', 'property', 'channel', 'check_in_date', 'check_out_date')
    # search_fields = ('property__name')


@admin.register(GuestImage)
class GuestImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'reservation_id', 'image')

class PaymentDateFilter(admin.SimpleListFilter):
    title = 'Due Date'
    parameter_name = 'due_date'

    def lookups(self, request, model_admin):
        return (
            ('today', 'Today'),
            ('tomorrow', 'Tomorrow'),
        )

    def queryset(self, request, queryset):
        today = date.today()
        if self.value() == 'today':
            return queryset.filter(expected_payment_date__date=today)
        if self.value() == 'tomorrow':
            return queryset.filter(expected_payment_date__date=today + timedelta(days=1))

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'amount','type', 'is_paid', 'expected_payment_date')
    list_filter = ('booking_id','is_paid', PaymentDateFilter, 'expected_payment_date')


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ('id', 'unique_id', 'first_name', 'last_name', 'email', 'property', 'check_in_date', 'check_out_date', 'created_at')
    list_filter = ('property', 'check_in_date', 'check_out_date', 'created_at')
    search_fields = ('first_name', 'last_name', 'email')

@admin.register(EnquiryImage)
class EnquiryImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'enquiry_id', 'image')    

@admin.register(EnquiryDocument)
class EnquiryDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'enquiry_id', 'name', 'file_type')

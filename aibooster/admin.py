import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import BoosterLead, ImageJob, ListingReport, Order


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in user-entered text."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@admin.register(BoosterLead)
class BoosterLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'feature', 'source_url', 'created_at')
    list_filter = ('feature',)
    search_fields = ('email',)
    date_hierarchy = 'created_at'
    actions = ['export_csv']

    @admin.action(description='Export selected leads to CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="booster-leads.csv"'
        writer = csv.writer(response)
        writer.writerow(['Name', 'Email', 'Feature', 'Source URL', 'IP address', 'Created at'])
        for lead in queryset.order_by('-created_at'):
            writer.writerow([
                _csv_safe(lead.name), _csv_safe(lead.email), lead.get_feature_display(),
                _csv_safe(lead.source_url), lead.ip_address or '',
                lead.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response


@admin.register(ImageJob)
class ImageJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'cost_cents', 'input_tokens', 'output_tokens', 'source_url', 'created_at')
    list_filter = ('status',)
    date_hierarchy = 'created_at'

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ListingReport)
class ListingReportAdmin(admin.ModelAdmin):
    list_display = ('source_url', 'platform', 'status', 'cost_cents', 'created_at')
    list_filter = ('platform', 'status')
    date_hierarchy = 'created_at'

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'status', 'quantity', 'amount_display', 'customer_email', 'created_at', 'paid_at')
    list_filter = ('kind', 'status')
    search_fields = ('customer_email', 'stripe_session_id')
    date_hierarchy = 'created_at'
    readonly_fields = [f.name for f in Order._meta.fields]

    @admin.display(description='Amount')
    def amount_display(self, obj):
        return f'{obj.amount_total / 100:.2f} {obj.currency.upper()}'

    def has_add_permission(self, request):
        return False

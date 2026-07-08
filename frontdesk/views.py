import datetime
import calendar
import json
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.views import View
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from xhtml2pdf import pisa

from booking.models import Booking, Enquiry
from property.models import Property, PropertyBlockDate
from tasks.models import Task
from accounts.utils import get_visible_user_ids
from .models import HousekeepingStatus

# Display label/slug for each cleaning status in the print report — status
# can be None (see `status = saved_statuses.get(prop.id)` in _fd_data above),
# meaning the host hasn't set one yet for this date.
HK_PRINT_STATUS_LABELS = {
    'Dirty': 'Dirty',
    'In-Progress': 'In-Progress',
    'Clean-Uninspected': 'Clean-Uninspected',
    'Clean-Inspected': 'Clean-Inspected',
    'Clean-Ready': 'Clean-Ready',
    'Out-of-Service': 'Out-of-Service',
    None: 'Not Set',
}
HK_PRINT_STATUS_SLUGS = {
    'Dirty': 'dirty',
    'In-Progress': 'in-progress',
    'Clean-Uninspected': 'clean-uninspected',
    'Clean-Inspected': 'clean-inspected',
    'Clean-Ready': 'clean-ready',
    'Out-of-Service': 'out-of-service',
    None: 'unset',
}


def _resolve_date(request):
    """Return the target date from ?date= or fall back to today."""
    date_param = request.GET.get('date')
    if date_param:
        try:
            return datetime.datetime.strptime(date_param, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass
    return request.user.get_local_date()


def _fd_data(request, target_date):
    """Shared query logic: returns all KPI + lists for a given date."""
    user_ids = get_visible_user_ids(request.user)

    active_properties = Property.objects.filter(
        created_by__in=user_ids, status='Active'
    )
    total_active = active_properties.count()

    active_bookings = Booking.objects.filter(
        property__created_by__in=user_ids,
        property__status='Active'
    ).exclude(status='cancelled')

    # In-house for target_date. check_out_date is exclusive here: a guest
    # checking out today has already left, so that property is not in-house
    # for today even though it was occupied through last night.
    inhouse_property_ids = set(active_bookings.filter(
        check_in_date__lte=target_date,
        check_out_date__gt=target_date
    ).values_list('property_id', flat=True))

    blocked_property_ids = set(PropertyBlockDate.objects.filter(
        property__created_by__in=user_ids,
        property__status='Active',
        is_active=True,
        start_date__lte=target_date,
        end_date__gte=target_date
    ).values_list('property_id', flat=True))

    total_inhouse = len(inhouse_property_ids)
    total_occupied = len(inhouse_property_ids | blocked_property_ids)
    total_vacant = total_active - total_occupied
    occupancy_pct = round((total_occupied / total_active * 100), 2) if total_active > 0 else 0

    # RevPAR = room revenue earned for target_date's night / total available rooms.
    # A booking earns a night's revenue for every date from check_in_date up to
    # (but excluding) check_out_date — the checkout date itself isn't a paid night.
    revenue_bookings = active_bookings.filter(
        check_in_date__lte=target_date,
        check_out_date__gt=target_date
    )
    room_revenue = revenue_bookings.aggregate(total=Sum('price_per_night'))['total'] or 0
    revpar = round(room_revenue / total_active, 2) if total_active > 0 else 0

    total_checkin = active_bookings.filter(check_in_date=target_date).count()
    total_checkout = active_bookings.filter(check_out_date=target_date).count()

    total_cancellations = Booking.objects.filter(
        property__created_by__in=user_ids,
        property__status='Active',
        status='cancelled',
        check_in_date__lte=target_date,
        check_out_date__gte=target_date
    ).count()

    total_booked = Booking.objects.filter(
        property__created_by__in=user_ids,
        created_at__date=target_date
    ).exclude(status='cancelled').count()

    total_tasks = Task.objects.filter(
        created_by__in=user_ids,
        date=target_date
    ).count()

    total_enquiries = Enquiry.objects.filter(
        property__created_by__in=user_ids,
        created_at__date=target_date
    ).exclude(is_archive=True).count()

    # Check-ins / Check-outs lists
    checkins = list(active_bookings.filter(
        check_in_date=target_date
    ).select_related('property').order_by('check_in_time'))

    checkouts = list(active_bookings.filter(
        check_out_date=target_date
    ).select_related('property').order_by('check_out_time'))

    # Housekeeping
    properties = active_properties.prefetch_related('images').order_by('title')
    saved_statuses = {
        hs.property_id: hs.status
        for hs in HousekeepingStatus.objects.filter(property__in=properties, date=target_date)
    }
    housekeeping = []
    for prop in properties:
        is_occupied = prop.id in inhouse_property_ids
        is_blocked = prop.id in blocked_property_ids
        has_checkout = active_bookings.filter(
            property=prop, check_out_date=target_date
        ).exists()
        has_checkin = active_bookings.filter(
            property=prop, check_in_date=target_date
        ).exists()

        # A check-in today means the unit is occupied from today, so it's
        # not available regardless of whether a checkout also happens that
        # same day (same-day turnover) or the suggested cleaning status.
        available = not (has_checkin or is_occupied or is_blocked)

        # Only report a status once the user has actually saved one for this
        # date — otherwise the dropdown should show its "Select Status"
        # default rather than silently pre-selecting a guess.
        status = saved_statuses.get(prop.id)

        housekeeping.append({
            'id': str(prop.id),
            'title': prop.title,
            'status': status,
            'available': available,
            'has_checkin': has_checkin,
            'has_checkout': has_checkout,
            'price': float(prop.price_per_night or 0),
            'guest_max': prop.guest,
            'bed_type': prop.bed_type,
            'pet_friendly': prop.amenities.filter(name__icontains='pet').exists(),
            'image_url': prop.get_primary_image_url(),
        })

    return {
        'target_date': target_date,
        'day_name': target_date.strftime('%A'),
        'day_num': target_date.day,
        'month_name': target_date.strftime('%b'),
        'date_iso': target_date.isoformat(),
        'occupancy_pct': occupancy_pct,
        'revpar': revpar,
        'total_inhouse': total_inhouse,
        'total_checkin': total_checkin,
        'total_checkout': total_checkout,
        'total_cancellations': total_cancellations,
        'total_vacant': total_vacant,
        'total_active': total_active,
        'total_booked_today': total_booked,
        'total_tasks': total_tasks,
        'total_enquiries': total_enquiries,
        'checkins': checkins,
        'checkouts': checkouts,
        'housekeeping': housekeeping,
    }


class FrontdeskIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'frontend/frontdesk/frontdesk.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        target_date = _resolve_date(self.request)
        data = _fd_data(self.request, target_date)
        context.update(data)
        return context


# --- Housekeeping print report ---
# Mirrors the printpanel app's panel-shell + iframe-preview pattern (see
# printpanel/views.py + printpanel/templates/printpanel/print_panel.html),
# but scoped to a single date's housekeeping data instead of a calendar
# date range — there's nothing else for the user to configure here.

def _hk_print_context(request, format_type):
    target_date = _resolve_date(request)
    housekeeping = _fd_data(request, target_date)['housekeeping']

    # One flat table (already ordered by property title from _fd_data), with
    # the cleaning status shown as its own column rather than split into a
    # separate table per status.
    rows = [
        dict(h, status_label=HK_PRINT_STATUS_LABELS[h['status']], status_slug=HK_PRINT_STATUS_SLUGS[h['status']])
        for h in housekeeping
    ]

    total = len(housekeeping)
    available = sum(1 for h in housekeeping if h['available'])

    return {
        'format_type': format_type,
        'target_date': target_date,
        'rows': rows,
        'total_listings': total,
        'available_count': available,
        'not_available_count': total - available,
        'checkin_count': sum(1 for h in housekeeping if h['has_checkin']),
        'checkout_count': sum(1 for h in housekeeping if h['has_checkout']),
        'dirty_count': sum(1 for h in housekeeping if h['status'] == 'Dirty'),
        'progress_count': sum(1 for h in housekeeping if h['status'] == 'In-Progress'),
        'clean_count': sum(1 for h in housekeeping if h['status'] in ('Clean-Uninspected', 'Clean-Inspected', 'Clean-Ready')),
        'user': request.user,
        'now': timezone.now(),
        'brand_logo_src': request.build_absolute_uri(static('img/login/favhost_new_logo.png')),
    }


class HousekeepingPrintPanelView(LoginRequiredMixin, View):
    """Print panel shell: date field + Print/PDF actions, iframe preview."""
    template_name = 'frontend/frontdesk/print_panel.html'

    def get(self, request, *args, **kwargs):
        target_date = _resolve_date(request)
        preview_url = reverse('frontdesk:print-preview') + f'?date={target_date.isoformat()}'
        context = {
            'target_date': target_date,
            'preview_url': preview_url,
        }
        return render(request, self.template_name, context)


class HousekeepingPrintPreviewView(LoginRequiredMixin, View):
    """Renders the housekeeping report HTML for the panel's iframe."""

    def get(self, request, *args, **kwargs):
        context = _hk_print_context(request, format_type='html')
        return render(request, 'frontend/print/print_housekeeping.html', context)


class HousekeepingPrintPDFView(LoginRequiredMixin, View):
    """Generates the housekeeping report as a PDF via xhtml2pdf."""

    def get(self, request, *args, **kwargs):
        context = _hk_print_context(request, format_type='pdf')
        html_string = render_to_string('frontend/print/print_housekeeping.html', context, request=request)
        response = HttpResponse(content_type='application/pdf')
        filename = f"housekeeping-{context['target_date'].isoformat()}.pdf"
        if request.GET.get('download'):
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        else:
            response['Content-Disposition'] = f'inline; filename="{filename}"'
        pisa_status = pisa.CreatePDF(html_string, dest=response, encoding='utf-8')
        if pisa_status.err:
            return HttpResponse('PDF generation error', status=500)
        return response


# --- API Views ---

class FrontdeskSummaryAPI(LoginRequiredMixin, View):
    def get(self, request):
        target_date = _resolve_date(request)
        data = _fd_data(request, target_date)
        return JsonResponse({
            'occupancy_pct': data['occupancy_pct'],
            'revpar': data['revpar'],
            'total_inhouse': data['total_inhouse'],
            'total_checkin': data['total_checkin'],
            'total_checkout': data['total_checkout'],
            'total_cancellations': data['total_cancellations'],
            'total_vacant': data['total_vacant'],
            'total_active': data['total_active'],
            'total_booked_today': data['total_booked_today'],
            'total_tasks': data['total_tasks'],
            'total_enquiries': data['total_enquiries'],
            'date_iso': data['date_iso'],
            'day_name': data['day_name'],
            'day_num': data['day_num'],
            'month_name': data['month_name'],
        })


class CheckInsAPI(LoginRequiredMixin, View):
    def get(self, request):
        target_date = _resolve_date(request)
        user_ids = get_visible_user_ids(request.user)
        checkins = Booking.objects.filter(
            property__created_by__in=user_ids,
            property__status='Active',
            check_in_date=target_date
        ).exclude(status='cancelled').select_related('property').order_by('check_in_time')

        data = []
        for b in checkins:
            data.append({
                'id': str(b.id),
                'booking_id': b.booking_id,
                'guest_name': f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest',
                'email': b.email or '',
                'phone': b.phone or '',
                'property_title': b.property.title,
                'check_in_time': str(b.check_in_time) if b.check_in_time else '',
                'image_url': b.property.get_primary_image_url() if hasattr(b.property, 'get_primary_image_url') else '',
            })
        return JsonResponse({'data': data})


class CheckOutsAPI(LoginRequiredMixin, View):
    def get(self, request):
        target_date = _resolve_date(request)
        user_ids = get_visible_user_ids(request.user)
        checkouts = Booking.objects.filter(
            property__created_by__in=user_ids,
            property__status='Active',
            check_out_date=target_date
        ).exclude(status='cancelled').select_related('property').order_by('check_out_time')

        data = []
        for b in checkouts:
            data.append({
                'id': str(b.id),
                'booking_id': b.booking_id,
                'guest_name': f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest',
                'email': b.email or '',
                'phone': b.phone or '',
                'property_title': b.property.title,
                'check_out_time': str(b.check_out_time) if b.check_out_time else '',
                'image_url': b.property.get_primary_image_url() if hasattr(b.property, 'get_primary_image_url') else '',
            })
        return JsonResponse({'data': data})


class HousekeepingAPI(LoginRequiredMixin, View):
    def get(self, request):
        target_date = _resolve_date(request)
        user_ids = get_visible_user_ids(request.user)

        active_properties = Property.objects.filter(
            created_by__in=user_ids, status='Active'
        )

        active_bookings = Booking.objects.filter(
            property__created_by__in=user_ids,
            property__status='Active'
        ).exclude(status='cancelled')

        # check_out_date is exclusive: a guest checking out today has
        # already left, so the property is not in-house today.
        inhouse_property_ids = set(active_bookings.filter(
            check_in_date__lte=target_date,
            check_out_date__gt=target_date
        ).values_list('property_id', flat=True))

        blocked_property_ids = set(PropertyBlockDate.objects.filter(
            property__created_by__in=user_ids,
            property__status='Active',
            is_active=True,
            start_date__lte=target_date,
            end_date__gte=target_date
        ).values_list('property_id', flat=True))

        saved_statuses = {
            hs.property_id: hs.status
            for hs in HousekeepingStatus.objects.filter(property__in=active_properties, date=target_date)
        }

        data = []
        for prop in active_properties:
            is_occupied = prop.id in inhouse_property_ids
            is_blocked = prop.id in blocked_property_ids
            has_checkout = active_bookings.filter(
                property=prop, check_out_date=target_date
            ).exists()
            has_checkin = active_bookings.filter(
                property=prop, check_in_date=target_date
            ).exists()

            # A check-in today means the unit is occupied from today, so it's
            # not available regardless of whether a checkout also happens that
            # same day (same-day turnover) or the suggested cleaning status.
            available = not (has_checkin or is_occupied or is_blocked)

            # Only report a status once the user has actually saved one for this
            # date — otherwise the dropdown should show its "Select Status"
            # default rather than silently pre-selecting a guess.
            status = saved_statuses.get(prop.id)

            data.append({
                'id': str(prop.id),
                'title': prop.title,
                'status': status,
                'available': available,
                'has_checkin': has_checkin,
                'has_checkout': has_checkout,
                'price': float(prop.price_per_night or 0),
                'guest_max': prop.guest,
                'bed_type': prop.bed_type,
                'pet_friendly': prop.amenities.filter(name__icontains='pet').exists(),
                'image_url': prop.get_primary_image_url() if hasattr(prop, 'get_primary_image_url') else '',
            })

        return JsonResponse({'data': data})

    def post(self, request):
        user_ids = get_visible_user_ids(request.user)
        try:
            body = json.loads(request.body)
            property_id = body.get('property_id')
            status = body.get('status')
            date_str = body.get('date')
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        valid_statuses = [s[0] for s in HousekeepingStatus.STATUS_CHOICES]
        if status not in valid_statuses:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        if date_str:
            try:
                target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Invalid date'}, status=400)
        else:
            target_date = request.user.get_local_date()

        try:
            prop = Property.objects.get(id=property_id, created_by__in=user_ids)
        except Property.DoesNotExist:
            return JsonResponse({'error': 'Property not found'}, status=404)

        HousekeepingStatus.objects.update_or_create(
            property=prop,
            date=target_date,
            defaults={'status': status}
        )
        return JsonResponse({'ok': True})
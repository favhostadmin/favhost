import datetime
import calendar
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.views import View
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone

from booking.models import Booking, Payment, Enquiry
from property.models import Property, PropertyBlockDate
from tasks.models import Task
from accounts.utils import get_visible_user_ids


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

    # In-house for target_date
    inhouse_property_ids = set(active_bookings.filter(
        check_in_date__lte=target_date,
        check_out_date__gte=target_date
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

    paid_payments = Payment.objects.filter(
        booking__property__created_by__in=user_ids,
        is_paid=True
    ).exclude(type__in=['Refundable deposit', 'Refundable to guest'])
    total_revenue = paid_payments.aggregate(total=Sum('amount'))['total'] or 0
    revpar = round(total_revenue / total_active, 2) if total_active > 0 else 0

    total_checkin = active_bookings.filter(check_in_date=target_date).count()
    total_checkout = active_bookings.filter(check_out_date=target_date).count()

    total_cancellations = Booking.objects.filter(
        property__created_by__in=user_ids,
        status='cancelled',
        check_in_date__lte=target_date,
        check_out_date__gte=target_date
    ).count()

    total_booked = Booking.objects.filter(
        property__created_by__in=user_ids,
        created_at__date=target_date
    ).exclude(status='cancelled').count()

    total_tasks = Task.objects.filter(
        created_by__in=user_ids, completed=False
    ).count()

    total_inquiries = Enquiry.objects.filter(
        property__created_by__in=user_ids,
        is_archive=False, is_booked=False
    ).count()

    # Check-ins / Check-outs lists
    checkins = list(active_bookings.filter(
        check_in_date=target_date
    ).select_related('property').order_by('check_in_time'))

    checkouts = list(active_bookings.filter(
        check_out_date=target_date
    ).select_related('property').order_by('check_out_time'))

    # Housekeeping
    properties = active_properties.prefetch_related('images').order_by('title')
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

        if is_occupied and has_checkout:
            suggested_status = 'Dirty'
            available = False
        elif is_occupied:
            suggested_status = 'In-Progress'
            available = False
        elif is_blocked:
            suggested_status = 'Out-of-Service'
            available = False
        elif has_checkin:
            suggested_status = 'Clean-Ready'
            available = True
        else:
            suggested_status = 'Clean-Inspected'
            available = True

        housekeeping.append({
            'id': str(prop.id),
            'title': prop.title,
            'status': suggested_status,
            'available': available,
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
        'total_booked_today': total_booked,
        'total_tasks': total_tasks,
        'total_inquiries': total_inquiries,
        'checkins': checkins,
        'checkouts': checkouts,
        'housekeeping': housekeeping,
    }


class FrontdeskIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'frontend/frontdesk/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        target_date = _resolve_date(self.request)
        data = _fd_data(self.request, target_date)
        context.update(data)
        return context


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
            'total_booked_today': data['total_booked_today'],
            'total_tasks': data['total_tasks'],
            'total_inquiries': data['total_inquiries'],
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

        inhouse_property_ids = set(active_bookings.filter(
            check_in_date__lte=target_date,
            check_out_date__gte=target_date
        ).values_list('property_id', flat=True))

        blocked_property_ids = set(PropertyBlockDate.objects.filter(
            property__created_by__in=user_ids,
            property__status='Active',
            is_active=True,
            start_date__lte=target_date,
            end_date__gte=target_date
        ).values_list('property_id', flat=True))

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

            if is_occupied and has_checkout:
                suggested_status = 'Dirty'
                available = False
            elif is_occupied:
                suggested_status = 'In-Progress'
                available = False
            elif is_blocked:
                suggested_status = 'Out-of-Service'
                available = False
            elif has_checkin:
                suggested_status = 'Clean-Ready'
                available = True
            else:
                suggested_status = 'Clean-Inspected'
                available = True

            data.append({
                'id': str(prop.id),
                'title': prop.title,
                'status': suggested_status,
                'available': available,
                'price': float(prop.price_per_night or 0),
                'guest_max': prop.guest,
                'bed_type': prop.bed_type,
                'pet_friendly': prop.amenities.filter(name__icontains='pet').exists(),
                'image_url': prop.get_primary_image_url() if hasattr(prop, 'get_primary_image_url') else '',
            })

        return JsonResponse({'data': data})
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone
from django.urls import reverse
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from accounts import currency

from booking.models import Booking, Enquiry
from property.models import Property, PropertyBlockDate
from tasks.models import Task
from accounts.utils import get_visible_user_ids

CALENDAR_URL_NAMES = {
    'month': 'calendar-month',
    'week': 'calendar-week',
    'day': 'calendar-day',
    'timeline': 'calendar',
    'list': 'calendar-list-view',
}

# Fixed span (in days, inclusive of the start date) used to derive end_date
# for each view type, so the printed range always matches what that view
# naturally shows instead of an arbitrary user-picked range.
VIEW_RANGE_DAYS = {
    'month': 30,
    'week': 7,
    'day': 1,
    'timeline': 30,
    'list': 30,
}


def _resolve_date_range(view_type, start_date_str, today):
    """Resolve start/end date from a single start date, sized by view type."""
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = today
    else:
        start_date = today

    days = VIEW_RANGE_DAYS.get(view_type, 30)
    end_date = start_date + timedelta(days=days - 1)
    return start_date, end_date


class PrintPanelView(LoginRequiredMixin, View):
    """Print panel editor with options sidebar and preview."""
    template_name = 'printpanel/print_panel.html'

    def get(self, request, *args, **kwargs):
        user = request.user
        today = user.get_local_date()

        view_type = request.GET.get('view', 'month')
        start_date_str = request.GET.get('start_date')
        start_date, end_date = _resolve_date_range(view_type, start_date_str, today)

        properties = Property.objects.filter(
            created_by__in=get_visible_user_ids(user),
            status='Active'
        )

        preview_url = (
            reverse('printpanel:preview')
            + f'?view={view_type}&start_date={start_date.isoformat()}'
            + f'&end_date={end_date.isoformat()}'
            + '&show_header=1&show_summary=1'
        )

        calendar_url_name = CALENDAR_URL_NAMES.get(view_type, 'calendar')
        close_url = reverse(calendar_url_name) + f'?month={start_date.month}&year={start_date.year}'

        context = {
            'view_type': view_type,
            'start_date': start_date,
            'end_date': end_date,
            'properties': properties,
            'preview_url': preview_url,
            'close_url': close_url,
            'user': user,
            'today': today,
        }
        return render(request, self.template_name, context)


class PrintPreviewView(LoginRequiredMixin, View):
    """Return the rendered HTML preview for the print panel iframe."""

    def get(self, request, *args, **kwargs):
        return _render_print_output(request, format_type='html')


class PrintPDFView(LoginRequiredMixin, View):
    """Generate and return the PDF."""

    def get(self, request, *args, **kwargs):
        return _render_print_output(request, format_type='pdf')


def _render_print_output(request, format_type='html'):
    """Shared logic to build context and render HTML or PDF."""
    user = request.user
    today = user.get_local_date()

    view_type = request.GET.get('view', 'month')
    start_date_str = request.GET.get('start_date')
    show_header = request.GET.get('show_header', '1') == '1'
    show_summary = request.GET.get('show_summary', '1') == '1'

    start_date, end_date = _resolve_date_range(view_type, start_date_str, today)

    properties = Property.objects.filter(
        created_by__in=get_visible_user_ids(user),
        status='Active'
    )

    bookings_qs = Booking.objects.filter(
        property__created_by__in=get_visible_user_ids(user),
        check_in_date__lte=end_date,
        check_out_date__gte=start_date
    ).exclude(status='cancelled').select_related('property', 'channel').prefetch_related('images', 'payments')

    tasks_qs = Task.objects.filter(
        property__created_by__in=get_visible_user_ids(user),
        date__lte=end_date,
        date__gte=start_date,
        completed=False
    ).select_related('property').order_by('date', 'time')

    enquiries_qs = Enquiry.objects.filter(
        property__created_by__in=get_visible_user_ids(user),
        check_in_date__lte=end_date,
        check_out_date__gte=start_date,
        is_archive=False
    ).select_related('property')

    blocked_qs = PropertyBlockDate.objects.filter(
        property__created_by__in=get_visible_user_ids(user),
        start_date__lte=end_date,
        end_date__gte=start_date,
        is_active=True
    ).select_related('property')

    delta = (end_date - start_date).days
    date_list = [start_date + timedelta(days=i) for i in range(delta + 1)]

    property_data = []
    for prop in properties:
        prop_bookings = [b for b in bookings_qs if str(b.property_id) == str(prop.id)]
        prop_tasks = [t for t in tasks_qs if str(t.property_id) == str(prop.id)]
        prop_enquiries = [e for e in enquiries_qs if str(e.property_id) == str(prop.id)]
        prop_blocks = [bl for bl in blocked_qs if str(bl.property_id) == str(prop.id)]

        days_data = []
        for d in date_list:
            day_bookings = [b for b in prop_bookings if b.check_in_date <= d < b.check_out_date]
            day_tasks = [t for t in prop_tasks if t.date == d]
            day_enquiries = [e for e in prop_enquiries if e.check_in_date <= d <= e.check_out_date]
            day_blocks = [bl for bl in prop_blocks if bl.start_date <= d <= bl.end_date]
            total_payment = 0
            for b in day_bookings:
                for p in b.payments.all():
                    if p.expected_payment_date and p.expected_payment_date.date() == d and p.is_paid:
                        total_payment += float(p.amount)
            days_data.append({
                'date': d,
                'bookings': day_bookings,
                'tasks': day_tasks,
                'enquiries': day_enquiries,
                'blocks': day_blocks,
                'total_payment': total_payment,
            })

        property_data.append({
            'property': prop,
            'bookings': prop_bookings,
            'tasks': prop_tasks,
            'enquiries': prop_enquiries,
            'blocks': prop_blocks,
            'days_data': days_data,
        })

    # Day view: flatten bookings/tasks/payments for start_date across all
    # properties into single lists, so the template can show one clean
    # "no bookings/tasks/payments" message instead of repeating it once per
    # property that has nothing that day.
    day_view_bookings = []
    day_view_tasks = []
    day_view_payments = []
    if view_type == 'day':
        for b in bookings_qs:
            if b.check_in_date <= start_date < b.check_out_date:
                day_view_bookings.append({
                    'property': b.property.title,
                    'guest': f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest',
                    'check_in': b.check_in_date, 'check_out': b.check_out_date,
                    'channel': b.channel.name if b.channel else 'Direct',
                })
            for p in b.payments.all():
                if p.expected_payment_date and p.expected_payment_date.date() == start_date:
                    day_view_payments.append({
                        'property': b.property.title,
                        'guest': f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest',
                        'type': p.type or 'Payment',
                        'amount': p.amount,
                        'is_paid': p.is_paid,
                    })
        for t in tasks_qs:
            if t.date == start_date:
                day_view_tasks.append({
                    'property': t.property.title,
                    'task_type': t.task_type or 'other',
                    'details': t.details or '',
                })

    all_events = []
    for b in bookings_qs:
        guest_name = f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest'
        prop_title = b.property.title if b.property else ''
        all_events.append({
            'date': b.check_in_date, 'type': 'Check In', 'property': prop_title,
            'guest': guest_name, 'details': f"{b.check_in_date} - {b.check_out_date}", 'channel': b.channel.name if b.channel else '',
        })
        all_events.append({
            'date': b.check_out_date, 'type': 'Check Out', 'property': prop_title,
            'guest': guest_name, 'details': '', 'channel': '',
        })
        for p in b.payments.all():
            pay_date = p.expected_payment_date.date() if p.expected_payment_date else None
            if pay_date:
                all_events.append({
                    'date': pay_date, 'type': 'Payment', 'property': prop_title,
                    'guest': guest_name, 'details': f"{currency.money(p.amount, request.user.currency)} {'Paid' if p.is_paid else 'Pending'}", 'channel': '',
                })
    for t in tasks_qs:
        prop_title = t.property.title if t.property else ''
        all_events.append({
            'date': t.date, 'type': 'Task', 'property': prop_title,
            'guest': '', 'details': t.details or t.task_type or '', 'channel': '',
        })
    all_events.sort(key=lambda e: (e['date'] or today, e['type']))

    week_bands = {'reservations': [], 'payments': [], 'tasks': []}
    for b in bookings_qs:
        guest_name = f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest'
        nights = (min(b.check_out_date, end_date) - max(b.check_in_date, start_date)).days
        week_bands['reservations'].append({
            'property': b.property.title,
            'guest': guest_name,
            'check_in': b.check_in_date, 'check_out': b.check_out_date,
            'nights': max(1, nights), 'color': b.channel.color if b.channel else '#3b82f6',
        })
        for p in b.payments.all():
            due_date = p.expected_payment_date.date() if p.expected_payment_date else None
            if due_date and start_date <= due_date <= end_date:
                week_bands['payments'].append({
                    'property': b.property.title,
                    'guest': guest_name,
                    'type': p.type or 'Payment',
                    'due_date': due_date,
                    'amount': p.amount,
                    'is_paid': p.is_paid,
                })
    for t in tasks_qs:
        week_bands['tasks'].append({
            'property': t.property.title, 'details': t.details or '',
            'task_type': t.task_type or 'other',
            'date': t.date, 'color': '#059669',
        })

    context = {
        'view_type': view_type,
        'format_type': format_type,
        'start_date': start_date,
        'end_date': end_date,
        'properties': properties,
        'property_data': property_data,
        'date_list': date_list,
        'all_events': all_events,
        'week_bands': week_bands,
        'day_view_bookings': day_view_bookings,
        'day_view_tasks': day_view_tasks,
        'day_view_payments': day_view_payments,
        'user': user,
        'today': today,
        'now': timezone.now(),
        'total_bookings': bookings_qs.count(),
        'total_tasks': tasks_qs.count(),
        'show_header': show_header,
        'show_summary': show_summary,
        'brand_logo_src': request.build_absolute_uri(static('img/header/favhost.png')),
    }

    if format_type == 'pdf':
        html_string = render_to_string('frontend/print/print_calendar.html', context, request=request)
        response = HttpResponse(content_type='application/pdf')
        filename = f"calendar-{view_type}-{start_date.isoformat()}-to-{end_date.isoformat()}.pdf"
        if request.GET.get('download'):
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        else:
            response['Content-Disposition'] = f'inline; filename="{filename}"'
        pisa_status = pisa.CreatePDF(html_string, dest=response, encoding='utf-8')
        if pisa_status.err:
            return HttpResponse('PDF generation error', status=500)
        return response

    return render(request, 'frontend/print/print_calendar.html', context)

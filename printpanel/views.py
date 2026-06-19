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
import calendar as cal_mod

from booking.models import Booking, Enquiry
from property.models import Property, PropertyBlockDate
from tasks.models import Task
from accounts.utils import get_visible_user_ids


class PrintPanelView(LoginRequiredMixin, View):
    """Print panel editor with options sidebar and preview."""
    template_name = 'printpanel/print_panel.html'

    def get(self, request, *args, **kwargs):
        user = request.user
        today = user.get_local_date()

        view_type = request.GET.get('view', 'month')
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                start_date = today
                end_date = today + timedelta(days=30)
        else:
            _, last_day = cal_mod.monthrange(today.year, today.month)
            start_date = today.replace(day=1)
            end_date = today.replace(day=last_day)

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

        context = {
            'view_type': view_type,
            'start_date': start_date,
            'end_date': end_date,
            'properties': properties,
            'preview_url': preview_url,
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
    end_date_str = request.GET.get('end_date')
    show_header = request.GET.get('show_header', '1') == '1'
    show_summary = request.GET.get('show_summary', '1') == '1'

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = today
            end_date = today + timedelta(days=30)
    else:
        _, last_day = cal_mod.monthrange(today.year, today.month)
        start_date = today.replace(day=1)
        end_date = today.replace(day=last_day)

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
                    'guest': guest_name, 'details': f"${float(p.amount):.2f} {'Paid' if p.is_paid else 'Pending'}", 'channel': '',
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
        has_pay = b.payments.exists()
        nights = (min(b.check_out_date, end_date) - max(b.check_in_date, start_date)).days
        week_bands['payments' if has_pay else 'reservations'].append({
            'property': b.property.title,
            'guest': f"{b.first_name or ''} {b.last_name or ''}".strip() or 'Guest',
            'check_in': b.check_in_date, 'check_out': b.check_out_date,
            'nights': max(1, nights), 'color': b.channel.color if b.channel else '#3b82f6',
        })
    for t in tasks_qs:
        week_bands['tasks'].append({
            'property': t.property.title, 'details': t.details or t.task_type or '',
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

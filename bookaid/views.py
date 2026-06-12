from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.generic import TemplateView
from django.views.generic.list import ListView
from django.db.models import Q
from django.db.models import Prefetch
from django.db.models.functions import Concat
from django.http import JsonResponse
import datetime
from collections import defaultdict

from booking.models import Booking, BookingChannel, Payment, Enquiry
from property.models import Property, PropertyChannel, PropertyBlockDate
from tasks.models import Task
from django.db.models import Sum, Count
from django.utils import timezone
from django.db.models.functions import ExtractYear, ExtractMonth
from django.utils.safestring import mark_safe
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.views.decorators.http import require_POST
from .utils import calculateTotalPayment
from accounts.utils import get_visible_user_ids
from django.contrib.staticfiles.storage import staticfiles_storage

class HostDashboardAPIView(LoginRequiredMixin, TemplateView):
    template_name = 'frontend/host/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_type = self.request.GET.get('type', '') 
        # print('selected_type==>',selected_type)
        context['selected_type'] = selected_type
        context['active_listings_count'] = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user), status='Active').count()

        total_revenue_agg = Payment.objects.filter(
            booking__property__created_by__in=get_visible_user_ids(self.request.user),
            is_paid=True
        ).exclude(
            type__in=['Refundable deposit', 'Refundable to guest']
        ).aggregate(total=Sum('amount'))
        context['total_revenue'] = total_revenue_agg['total'] or 0

        context['pending_tasks_count'] = Task.objects.filter(created_by__in=get_visible_user_ids(self.request.user), completed=False).count()
        context['new_enquiry_list'] = Enquiry.objects.filter(property__created_by__in=get_visible_user_ids(self.request.user), is_archive=False, is_booked=False)[:6]

        today = self.request.user.get_local_date()

        if selected_type == 'tomorrow':
            target_date = today + datetime.timedelta(days=1)
        else:
            target_date = today

        active_bookings = Booking.objects.filter(
            property__created_by__in=get_visible_user_ids(self.request.user), 
            property__status='Active'
        ).exclude(status='cancelled')

        total_checkin = active_bookings.filter(check_in_date=target_date).count()
        total_checkout = active_bookings.filter(check_out_date=target_date).count()
        total_tasks = Task.objects.filter(
            created_by__in=get_visible_user_ids(self.request.user),
            date=target_date,
            completed=False
        ).count()
        
        total_payment = Payment.objects.filter(
            booking__property__created_by__in=get_visible_user_ids(self.request.user),
            expected_payment_date__date=target_date,
            is_paid=False
        ).exclude(
            type__in = ['Refundable deposit', 'Cleaning Fee', 'Application Fee', 'Refundable to guest']
        ).count()

        # Determine which properties are currently occupied by guests
        inhouse_property_ids = set(active_bookings.filter(
            check_in_date__lte=target_date,
            check_out_date__gte=target_date
        ).values_list('property_id', flat=True))

        # Determine which properties are manually blocked on this date
        blocked_property_ids = set(PropertyBlockDate.objects.filter(
            property__created_by__in=get_visible_user_ids(self.request.user),
            property__status='Active',
            is_active=True,
            start_date__lte=target_date,
            end_date__gte=target_date
        ).values_list('property_id', flat=True))

        total_inhouse = len(inhouse_property_ids)
        total_occupied = len(inhouse_property_ids | blocked_property_ids)
        total_active_count = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user), status='Active').count()
        total_vacant = total_active_count - total_occupied


        context['total_checkin'] = total_checkin
        context['total_checkout'] = total_checkout
        context['total_tasks'] = total_tasks
        context['total_payment'] = total_payment
        context['total_inhouse'] = total_inhouse
        context['total_vacant'] = total_vacant

        seven_days_ago = today - datetime.timedelta(days=7)
        context['recent_bookings'] = Booking.objects.filter(
            property__created_by=self.request.user,
            created_at__date__gte=seven_days_ago,
            created_at__date__lte=today
        ).exclude(status='cancelled').order_by('-created_at')

        current_year = timezone.now().year
        gross_qs = Booking.objects.filter(
            property__created_by=self.request.user,
            created_at__year=current_year
        ).exclude(status='cancelled')
        context['gross_bookings_amount'] = gross_qs.aggregate(total=Sum('price'))['total'] or 0
        channel_data = gross_qs.values('channel__name').annotate(
            count=Count('id'),
            total=Sum('price')
        ).order_by('-count')
        context['channel_labels'] = [c['channel__name'] or 'Direct' for c in channel_data]
        context['channel_counts'] = [c['count'] for c in channel_data]
        context['channel_amounts'] = [float(c['total'] or 0) for c in channel_data]
        context['channel_labels_json'] = mark_safe(json.dumps([c['channel__name'] or 'Direct' for c in channel_data]))
        context['channel_counts_json'] = mark_safe(json.dumps([c['count'] for c in channel_data]))
        context['channel_amounts_json'] = mark_safe(json.dumps([float(c['total'] or 0) for c in channel_data]))

        # --- Earning monthly for a year ---

        # 1) Determine selected year (query param ?year=YYYY, fallback to current year)
        selected_year_str = self.request.GET.get("year")

        try:
            selected_year = int(selected_year_str) if selected_year_str else current_year
        except ValueError:
            selected_year = current_year
        
        # print( 'current_year==>',current_year)
        # print( 'selected_year==>',selected_year)


        # 2) Month‑wise earnings from Payment for ALL years (only paid ones)
        qs = (
            Payment.objects
            .filter(
                booking__property__created_by__in=get_visible_user_ids(self.request.user),
                is_paid=True,
            )
            .exclude(type__in=['Refundable deposit', 'Refundable to guest'])
            .annotate(
                year=ExtractYear('expected_payment_date'),
                month=ExtractMonth('expected_payment_date'),
            )
            .values('year', 'month')
            .annotate(total=Sum('amount'))
            .order_by('year', 'month')
        )

        # print('qs==>',qs)

        # 3) Build {year: [12 month totals]} using SUM from query
        year_earnings = {}
        for row in qs:
            # print('row==>',row)
            y = row['year']
            m = row['month']      # 1–12
            if y is None or m is None:
                continue

            if y not in year_earnings:
                year_earnings[y] = [0] * 12

            # this is the dynamic sum for that month in that year
            year_earnings[y][m - 1] = float(row['total'])

        # 4) If selected_year has no payments, fall back to current_year
        if selected_year not in year_earnings and current_year in year_earnings:
            selected_year = current_year

        # 5) Final 12‑length list for the selected year
        monthly_earnings = year_earnings.get(selected_year, [0] * 12)


        # total_earnings = sum(monthly_earnings)
        # monthly_average = total_earnings / 12

        # Calculate total earnings up to today using the formula:
        # (Total revenue / (TODAY - Jan 1, YYYY)) * 30
        total_earnings = 0
        year_start = datetime.date(selected_year, 1, 1)
        today_date = today

        # print("year_start==>",year_start)
        # print("today_date==>",today_date)


        for month in range(1, 13):
            # Determine the last day of this month
            if month == 12:
                month_end = datetime.date(selected_year, 12, 31)
            else:
                month_end = datetime.date(selected_year, month + 1, 1) - datetime.timedelta(days=1)
            
            # Only include this month if it has fully or partially elapsed up to today
            if month_end <= today_date:
                total_earnings += monthly_earnings[month - 1]

        # Calculate days elapsed from Jan 1 to today
        days_elapsed = (today_date - year_start).days

        # print("days_elapsed==>",days_elapsed)

        if days_elapsed == 0:
            days_elapsed = 1  # Avoid division by zero on Jan 1

        # print("total_earnings==>",total_earnings)

        # Apply formula: (total_earnings / days_elapsed) * 30
        monthly_average = (total_earnings / days_elapsed) * 30 if days_elapsed > 0 else 0

        # print("monthly_average==>",monthly_average)
        

        # 6) Years for dropdown — use values_list + set for SQLite compatibility
        total_years = sorted(set(
            Booking.objects
            .filter(property__created_by__in=get_visible_user_ids(self.request.user))
            .exclude(status='cancelled')
            .values_list('check_in_date__year', flat=True)
        ))

        context['current_year'] = current_year
        context['selected_year'] = selected_year
        context['total_years'] = total_years
        context['year_earnings_json'] = mark_safe(json.dumps(year_earnings))
        context['monthly_earnings_js'] = mark_safe(json.dumps(monthly_earnings))
        context['monthly_average'] = format(monthly_average, '.2f')

        # --- Upcoming events (check-in, check-out, payment, tasks) grouped by date ---
        upcoming_month_str = self.request.GET.get("upcoming_month")
        upcoming_year_str = self.request.GET.get("upcoming_year")

        try:
            upcoming_month = int(upcoming_month_str) if upcoming_month_str else today.month
            if upcoming_month < 1 or upcoming_month > 12:
                upcoming_month = today.month
        except ValueError:
            upcoming_month = today.month

        try:
            upcoming_year = int(upcoming_year_str) if upcoming_year_str else today.year
        except ValueError:
            upcoming_year = today.year

        payments_qs = Payment.objects.filter(
            Q(expected_payment_date__year=upcoming_year, expected_payment_date__month=upcoming_month) |
            Q(payment_date__year=upcoming_year, payment_date__month=upcoming_month)
        )

        bookings = (
            Booking.objects
            .filter(
                Q(check_in_date__year=upcoming_year, check_in_date__month=upcoming_month) |
                Q(check_out_date__year=upcoming_year, check_out_date__month=upcoming_month),
                property__created_by__in=get_visible_user_ids(self.request.user)
            )
            .exclude(status='cancelled')
            .select_related('property', 'channel')
            .prefetch_related('images', Prefetch('payments', queryset=payments_qs))
        )

        tasks = (
            Task.objects
            .filter(
                created_by__in=get_visible_user_ids(self.request.user),
                property__created_by__in=get_visible_user_ids(self.request.user),
                date__gte=today,
                date__year=upcoming_year,
                date__month=upcoming_month,
                completed=False,
            )
            .select_related('property')
        )

        def status_for(d):
            diff = (d - today).days
            if diff < 0:
                return ("overdue", "Overdue")
            if diff == 0:
                return ("due-soon", "Due today")
            if diff <= 7:
                return ("due-soon", f"Due in {diff} days")
            return ("upcoming", f"Due in {diff} days")

        def get_property_image(prop, fallback=""):
            getter = getattr(prop, "get_primary_image_url", None)
            if callable(getter):
                try:
                    url = getter()
                except Exception:
                    url = ""
                if url:
                    return url
            return fallback

        event_groups = defaultdict(list)
        group_sort = {"Checkin": 1, "Checkout": 2, "Payment": 3, "Task": 4}

        for b in bookings:
            prop_img = b.images.filter(is_primary=True).first() or b.images.first()
            avatar = prop_img.image.url if prop_img else staticfiles_storage.url('img/common/default_user_icon.png')
            guest_name = f"{b.first_name or ''} {b.last_name or ''}".strip() or "Guest"
            property_image = get_property_image(b.property, avatar)
            guest_phone = " ".join([p for p in [b.country_code, b.phone] if p])
            guest_email = b.email or ""
            channel_name = b.channel.name if b.channel else ""
            stay_str = ""
            if b.check_in_date and b.check_out_date:
                nights = (b.check_out_date - b.check_in_date).days
                stay_str = f"{b.check_in_date:%b %d, %Y} - {b.check_out_date:%b %d, %Y} ({nights} nights)"

            if b.check_in_date and b.check_in_date.year == upcoming_year and b.check_in_date.month == upcoming_month:
                code, label = status_for(b.check_in_date)
                event_groups[b.check_in_date].append({
                    "date": b.check_in_date,
                    "group": "Checkin",
                    "title": "Check In",
                    "property": b.property.title,
                    "icon": "/img/property/checkin.png",
                    "guest_name": guest_name,
                    "guest_phone": guest_phone,
                    "guest_email": guest_email,
                    "stay": stay_str,
                    "channel_name": channel_name,
                    "avatar": avatar,
                    "property_image": property_image,
                    "status_code": code,
                    "status_label": label,
                    "status_class": "status-checkin",
                    "sort_key": group_sort["Checkin"],
                })

            if b.check_out_date and b.check_out_date.year == upcoming_year and b.check_out_date.month == upcoming_month:
                code, label = status_for(b.check_out_date)
                event_groups[b.check_out_date].append({
                    "date": b.check_out_date,
                    "group": "Checkout",
                    "title": "Check Out",
                    "property": b.property.title,
                    "icon": "img/property/checkout.png",
                    "guest_name": guest_name,
                    "guest_phone": guest_phone,
                    "guest_email": guest_email,
                    "stay": stay_str,
                    "channel_name": channel_name,
                    "avatar": avatar,
                    "property_image": property_image,
                    "status_code": code,
                    "status_label": label,
                    "status_class": "status-checkout",
                    "sort_key": group_sort["Checkout"],
                })

            for p in b.payments.all():
                if p.type in ['Refundable deposit', 'Cleaning Fee', 'Application Fee', 'Refundable to guest']:
                    continue
                pay_date = None
                if p.expected_payment_date:
                    pay_date = p.expected_payment_date.date()
                elif p.payment_date:
                    pay_date = p.payment_date.date()
                if not pay_date:
                    continue
                if pay_date.year != upcoming_year or pay_date.month != upcoming_month:
                    continue
                code, label = status_for(pay_date)
                if p.is_paid:
                    code, label = "paid", "Paid"
                event_groups[pay_date].append({
                    "date": pay_date,
                    "group": "Payment",
                    "title": "Payment",
                    "amount": float(p.amount),
                    "paid": p.is_paid,
                    "property": b.property.title,
                    "icon": "img/task/type/payment.svg",
                    "guest_name": guest_name,
                    "guest_phone": guest_phone,
                    "guest_email": guest_email,
                    "stay": stay_str,
                    "channel_name": channel_name,
                    "avatar": avatar,
                    "property_image": property_image,
                    "status_code": code,
                    "status_label": label,
                    "status_class": "status-payment",
                    "sort_key": group_sort["Payment"],
                })

        for t in tasks:
            if not t.date:
                continue
            code, label = status_for(t.date)
            title = "Task"
            status_class = "status-checkin"
            if t.task_type == "cleaning":
                title = "Cleaning"
                status_class = "status-cleaning"
            elif t.task_type == "maintenance":
                title = "Maintenance"
                status_class = "status-checkout"
            elif t.task_type == "payment":
                title = "Payment Task"
                status_class = "status-payment"

            t_prop_image = get_property_image(t.property, "")
            event_groups[t.date].append({
                "date": t.date,
                "group": "Task",
                "title": title,
                "property": t.property.title,
                "task_type": t.task_type,
                "icon": {
                    "cleaning": "img/task/type/cleaning.svg",
                    "maintenance": "img/task/type/maintenance.svg",
                    "payment": "img/task/type/payment.svg",
                }.get(t.task_type, "img/task/type/others.svg"),
                "guest_name": t.assigned_to or "Task",
                "guest_phone": t.phone or "",
                "guest_email": "",
                "stay": "",
                "channel_name": "",
                "avatar": staticfiles_storage.url('img/common/default_user_icon_1.png'),
                "property_image": t_prop_image,
                "status_code": "completed" if t.completed else code,
                "status_label": "Completed" if t.completed else label,
                "status_class": status_class,
                "sort_key": group_sort["Task"],
            })

        upcoming_groups = []
        for group_date in sorted(event_groups.keys()):
            if group_date >= today:
                group_code, group_label = status_for(group_date)
                items = sorted(event_groups[group_date], key=lambda e: e["sort_key"])
                upcoming_groups.append({
                    "date": group_date,
                    "status_label": group_label,
                    "status_code": group_code,
                    "items": items,
                })

        context["upcoming_month"] = upcoming_month
        context["upcoming_year"] = upcoming_year
        context["upcoming_groups"] = upcoming_groups
        return context


class CalenderAPIView(LoginRequiredMixin,ListView):
    model = Booking
    template_name = 'frontend/calender/calender.html'

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return self.get_bookings_data(request)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        properties = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user), status='Active' )

        rooms_list = []
        for prop in properties:
            rooms_list.append({
                'id': str(prop.id),
                'title': prop.title,
                'image': prop.get_primary_image_url(),
                'location': prop.location_display(),
                'price_per_night': float(prop.price_per_night or 0),
                'guest': prop.guest,
                'minimum_nights': prop.minimum_booking,
                'basePrice': float(prop.price_per_night),
                'weekendMultiplier': 1.0, 
                'slug': prop.slug,
                'detail_url': f"/property/detail/{prop.slug}/",
            })
        context['rooms_data'] = rooms_list
        context['bookings_data'] = []  # Initially empty, will be loaded by JS

        return context

    def get_bookings_data(self, request):
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        bookings_qs = Booking.objects.filter(
            property__created_by__in=get_visible_user_ids(request.user),
            check_in_date__lte=end_date,
            check_out_date__gte=start_date
        ).exclude(status='cancelled').select_related('property', 'channel').prefetch_related('images', 'payments')

        bookings_list = []
        for b in bookings_qs:
            guest_image = b.images.filter(is_primary=True).first() or b.images.first()
            guest_avatar_url = guest_image.image.url if guest_image else staticfiles_storage.url('img/common/default_user_icon.png')
            total_payment = calculateTotalPayment(b.id)

            if b.check_in_date and b.check_out_date:
                total_price = b.price
                # Deduct refundable deposit for manual bookings where it is included in the price
                if not b.external_uid and b.property.refundable_deposit:
                    total_price = total_price - b.property.refundable_deposit
                
                payment_dates = []
                payments_info = {}
                first_installment_amount = 0.0

                for p in b.payments.all():
                    if p.type in ['Refundable deposit', 'Cleaning Fee', 'Application Fee', 'Payment 1']:
                        first_installment_amount += float(p.amount)
                    if p.type in ['Refundable deposit', 'Cleaning Fee', 'Application Fee', 'Refundable to guest']:
                        continue
                    if p.expected_payment_date:
                        d_str = p.expected_payment_date.date().isoformat()
                        payment_dates.append(d_str)
                        payments_info[d_str] = {
                            'amount': float(p.amount),
                            'is_paid': p.is_paid,
                            'type': p.type or 'Payment'
                        }

                bookings_list.append({
                    'id': str(b.id),
                    'propertyId': str(b.property.id),
                    'price_per_night': float(b.price_per_night),
                    'totalPrice': float(total_price),
                    'totalPayment': float(total_payment),
                    'firstInstallment': float(first_installment_amount),
                    'start_date': b.check_in_date.isoformat(),
                    'end_date': b.check_out_date.isoformat(),
                    'guestName': f"{b.first_name or ''} {b.last_name or ''}".strip(),
                    'guestAvatar': guest_avatar_url,
                    'color': b.channel.color if b.channel else '#808080',
                    'channelIcon': b.channel.white_icon.url if b.channel and b.channel.white_icon else '',
                    'channelName': b.channel.name if b.channel else 'N/A',
                    'bookingId': b.booking_id or 'N/A',
                    'paymentDates': payment_dates,
                    'paymentsInfo': payments_info,
                })

        # Fetch blocked dates
        blocked_dates_qs = PropertyBlockDate.objects.filter(
            property__created_by__in=get_visible_user_ids(request.user),
            start_date__lte=end_date,
            end_date__gte=start_date
        ).select_related('property')

        for block in blocked_dates_qs:
            bookings_list.append({
                'id': f"block-{block.id}",
                'propertyId': str(block.property.id),
                'start_date': block.start_date.isoformat(),
                'end_date': block.end_date.isoformat(),
                'color': '#9ca3af',  # Gray color for blocked dates
                'type': 'blocked',
                'reason': block.reason
            })

        # Fetch tasks for the date range organized by date and property
        tasks_qs = Task.objects.filter(
            property__created_by__in=get_visible_user_ids(request.user),
            date__lte=end_date,
            date__gte=start_date,
            completed=False
        ).select_related('property').order_by('date', 'time')

        tasks_list = []
        for task in tasks_qs:
            tasks_list.append({
                'id': f"task-{task.id}",
                'propertyId': str(task.property.id),
                'date': task.date.isoformat() if task.date else None,
                'time': task.time.isoformat() if task.time else None,
                'task_type': task.task_type,
                'details': task.details or '',
                'assigned_to': task.assigned_to or '',
                'phone': task.phone or '',
                'completed': task.completed,
                'repeat': task.repeat,
                'repeat_till': task.repeat_till.isoformat() if task.repeat_till else None,
                'type': 'task',
                'color': {
                    'cleaning': '#10b981',
                    'maintenance': '#f59e0b',
                    'payment': '#3b82f6',
                    'other': '#8b5cf6'
                }.get(task.task_type, '#6b7280')
            })

        return JsonResponse({
            'bookings': bookings_list,
            'tasks': tasks_list
        })

# views.py
from datetime import date
from django.views.generic import ListView
from django.http import JsonResponse
from django.db.models import Prefetch

class CalendarListView(LoginRequiredMixin, ListView):
    model = Booking
    template_name = 'frontend/calender/calender-list-view.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_month'] = date.today()
        return ctx

    def get_queryset(self):
        # base queryset in case you still use object_list in template
        return (
            Booking.objects
            .filter(property__created_by__in=get_visible_user_ids(self.request.user))
            .exclude(status='cancelled')
            .select_related('property', 'channel')
            .prefetch_related('images', 'payments')
        )

    def get(self, request, *args, **kwargs):
        # AJAX JSON for list view
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            month = int(request.GET.get('month', date.today().month))
            year = int(request.GET.get('year', date.today().year))
            today = date.today()

            # Fetch bookings where check-in OR check-out is in the given month/year
            bookings = (
                Booking.objects
                .filter(
                    Q(property__created_by__in=get_visible_user_ids(request.user)),
                    Q(check_in_date__year=year, check_in_date__month=month) |
                    Q(check_out_date__year=year, check_out_date__month=month)
                )
                .exclude(status='cancelled')
                .select_related('property', 'channel')
                .prefetch_related(
                    'images',
                    Prefetch('payments', queryset=Payment.objects.filter(
                        expected_payment_date__year=year, expected_payment_date__month=month
                    ))
                )
            )

            tasks = (
                Task.objects
                .filter(
                    created_by__in=get_visible_user_ids(request.user),
                    property__created_by__in=get_visible_user_ids(request.user),
                    date__year=year,
                    date__month=month,
                )
                .select_related('property')
            )

            def status_for(d):
                diff = (d - today).days
                if diff < 0:
                    return ("overdue", "Overdue")
                if diff == 0:
                    return ("due-soon", "Due today")
                if diff <= 7:
                    return ("due-soon", f"Due in {diff} days")
                return ("upcoming", f"Due in {diff} days")

            events = []

            def format_guest_phone(country_code, phone):
                phone = (phone or "").strip()
                code = (country_code or "").strip()
                if not phone:
                    return ""
                if not code:
                    return phone
                # Ignore textual country codes like "in" and keep the stored phone only.
                if code.isalpha():
                    return phone
                if not code.startswith("+"):
                    code = f"+{code}"
                return f"{code} {phone}"

            # booking-based events
            for b in bookings:
                prop_img = b.images.filter(is_primary=True).first() or b.images.first()
                avatar = prop_img.image.url if prop_img else ""
                guest_name = f"{b.first_name or ''} {b.last_name or ''}".strip() or "Guest"
                stay_str = ""
                if b.check_in_date and b.check_out_date:
                    nights = (b.check_out_date - b.check_in_date).days
                    stay_str = f"{b.check_in_date:%b %d, %Y}—{b.check_out_date:%b %d, %Y} ({nights} nights)"

                # property image (prefer property’s own image helper if you have one)
                property_image = getattr(b.property, "get_primary_image_url", None)
                if callable(property_image):
                    property_image = property_image()
                else:
                    # fallback to first booking image
                    property_image = avatar or ""

                # Check‑out
                if b.check_out_date and b.check_out_date.year == year and b.check_out_date.month == month:
                    code, label = status_for(b.check_out_date)
                    events.append({
                        "date": b.check_out_date.isoformat(),
                        "group": "Checkout",
                        "title": "Check Out",
                        "property": b.property.title,
                        "location": b.property.city,
                        "guest_name": guest_name,
                        "guest_email": b.email or "",
                        "guest_phone": format_guest_phone(b.country_code, b.phone),
                        "stay": stay_str,
                        "avatar": avatar,
                        "property_image": property_image, 
                        "status_code": code,
                        "status_label": label,
                    })

                # Check‑in
                if b.check_in_date and b.check_in_date.year == year and b.check_in_date.month == month:
                    code, label = status_for(b.check_in_date)
                    events.append({
                        "date": b.check_in_date.isoformat(),
                        "group": "Checkin",
                        "title": "Check In",
                        "property": b.property.title,
                        "location": b.property.city,
                        "guest_name": guest_name,
                        "guest_email": b.email or "",
                        "guest_phone": format_guest_phone(b.country_code, b.phone),
                        "stay": stay_str,
                        "avatar": avatar,
                        "property_image": property_image,
                        "status_code": code,
                        "status_label": label,
                    })

                # Payments (from Payment model)
                for p in b.payments.all():
                    if p.type in ['Refundable deposit', 'Cleaning Fee', 'Application Fee', 'Refundable to guest']:
                        continue
                    pay_date = p.expected_payment_date.date() if p.expected_payment_date else (p.payment_date.date() if p.payment_date else today)
                    code, label = status_for(pay_date)
                    if p.is_paid:
                        code, label = "paid", "Paid"
                    events.append({
                        "date": pay_date.isoformat(),
                        "group": "Payment",
                        "title": "Payment",
                        "amount": float(p.amount),
                        "paid": p.is_paid,
                        "property": b.property.title,
                        "location": b.property.city,
                        "guest_name": guest_name,
                        "guest_email": b.email or "",
                        "guest_phone": format_guest_phone(b.country_code, b.phone),
                        "stay": stay_str,
                        "avatar": avatar,
                        "property_image": property_image,
                        "status_code": code,
                        "status_label": label,
                    })

            # Task events (from Task model)
            for t in tasks:
                if not t.date:
                    continue
                code, label = status_for(t.date)
                title = "Task"
                if t.task_type == "cleaning":
                    title = "Cleaning"
                elif t.task_type == "maintenance":
                    title = "Maintenance"
                elif t.task_type == "payment":
                    title = "Payment Task 💳"

                # property image for tasks
                t_prop_image = getattr(t.property, "get_primary_image_url", None)
                if callable(t_prop_image):
                    t_prop_image = t_prop_image()
                else:
                    t_prop_image = ""

                events.append({
                    "date": t.date.isoformat(),
                    "time": t.time.isoformat() if t.time else None,
                    "group": "Task",
                    "title": title,
                    "details": t.details or "",
                    "property": t.property.title,
                    "location": t.property.city,
                    "guest_name": t.assigned_to or "",
                    "guest_email": "",
                    "guest_phone": format_guest_phone(t.country_code, t.phone),
                    "guest_id": t.phone or "",
                    "avatar": "",
                    "property_image": t_prop_image,
                    "status_code": "completed" if t.completed else code,
                    "status_label": "Completed" if t.completed else label,
                })

            events.sort(key=lambda e: e["date"])
            return JsonResponse({"events": events})

        return super().get(request, *args, **kwargs)

@login_required
def channel_integration(request, property_id):
    property_obj = get_object_or_404(Property, pk=property_id, created_by__in=get_visible_user_ids(request.user))

    if request.method == 'POST':
        # --- Handle updates for existing channels ---
        existing_channels = PropertyChannel.objects.filter(property=property_obj)
        for channel in existing_channels:
            calendar_link = request.POST.get(f'calendar_link_{channel.id}')
            is_connected = request.POST.get(f'is_connected_{channel.id}') == 'on'

            # NEW: allow channel type to change when editing
            channel_type_id = request.POST.get(f'channel_type_{channel.id}')
            if channel_type_id:
                try:
                    channel_type_id = int(channel_type_id)
                except (TypeError, ValueError):
                    channel_type_id = None

            # Only update fields that actually changed
            changed = False
            if calendar_link is not None and channel.calendar_link != calendar_link:
                channel.calendar_link = calendar_link
                changed = True

            if channel.is_connected != is_connected:
                channel.is_connected = is_connected
                changed = True

            if channel_type_id and channel.channel_type_id != channel_type_id:
                channel.channel_type_id = channel_type_id
                changed = True

            if changed:
                channel.save()

        # --- Handle new channel additions ---
        new_channel_keys = [k for k in request.POST if k.startswith('new_channel_type_')]
        for key in new_channel_keys:
            timestamp = key.split('_')[-1]
            channel_type_id = request.POST.get(key)
            calendar_link = request.POST.get(f'new_calendar_link_{timestamp}')
            is_connected = request.POST.get(f'new_is_connected_{timestamp}') == 'on'

            if channel_type_id and calendar_link:
                PropertyChannel.objects.update_or_create(
                    property=property_obj,
                    channel_type_id=channel_type_id,
                    defaults={
                        'calendar_link': calendar_link,
                        'is_connected': is_connected
                    }
                )
            elif channel_type_id or calendar_link:
                messages.error(request, "Both channel name and calendar link are required for new integrations.")
                return redirect('channel_integration', property_id=property_id)

        messages.success(request, "Channel integrations saved successfully.")
        return redirect('channel_integration', property_id=property_id)

    channels = PropertyChannel.objects.filter(property=property_obj).select_related('channel_type')
    booking_channels = BookingChannel.objects.all()
    existing_channel_ids = channels.values_list('channel_type_id', flat=True)
    available_booking_channels = booking_channels.exclude(id__in=existing_channel_ids)

    context = {
        'property': property_obj,
        'channels': channels,
        'booking_channels': available_booking_channels,
        'all_booking_channels': booking_channels,
    }
    return render(request, 'frontend/channels/add.html', context)




@login_required
def toggle_channel_status(request, property_id, channel_id):
    """
    API endpoint to toggle the is_connected status of a PropertyChannel.
    """
    if request.method == 'POST':
        try:
            # Ensure the channel belongs to the user and property
            channel = get_object_or_404(PropertyChannel, pk=channel_id, property_id=property_id, property__created_by__in=get_visible_user_ids(request.user))
            
            # Flip the boolean status
            channel.is_connected = not channel.is_connected
            channel.save(update_fields=['is_connected'])

            status_text = "Connected" if channel.is_connected else "Disconnected"
            message = f"Channel '{channel.channel_type.name}' status updated to {status_text}."
            
            return JsonResponse({'success': True, 'is_connected': channel.is_connected, 'message': message})
        except PropertyChannel.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Channel not found.'}, status=404)
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

@require_POST
def contact_host(request):
    short_code = request.POST.get('host_short_code')
    MyUser = get_user_model()
    host = get_object_or_404(MyUser, short_code=short_code)

    first_name = request.POST.get('first_name')
    last_name = request.POST.get('last_name')
    sender_email = request.POST.get('email')
    phone = request.POST.get('phone')
    message_content = request.POST.get('message')

    subject = f"New Inquiry from {first_name} {last_name} via FavHost"
    email_body = f"""
    Hello {host.get_full_name() or host.username},

    You have received a new message from your public listing page.

    Sender Details:
    - Name: {first_name} {last_name}
    - Email: {sender_email}
    - Phone: {phone}

    Message:
    {message_content}
    """

    try:
        email = EmailMessage(
            subject=subject,
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[host.email],
            reply_to=[sender_email],
        )
        email.send(fail_silently=False)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


class ManualSyncAPIView(LoginRequiredMixin, View):
    """
    API endpoint to manually trigger iCal synchronization for all 
    connected channels of the current user.
    """
    def post(self, request, *args, **kwargs):
        from booking.utils import sync_property_channel
        
        # Filter for connected channels on properties owned by the current user
        channels = PropertyChannel.objects.filter(
            property__created_by__in=get_visible_user_ids(request.user), 
            is_connected=True
        )
        count = channels.count()
        for channel in channels:
            sync_property_channel.delay(channel.id)
            
        return JsonResponse({'success': True, 'message': f'Sync started for {count} channels.'})

@login_required
def delete_channel(request, property_id, channel_id):
    """
    API endpoint to delete a PropertyChannel.
    """
    if request.method == 'POST':
        try:
            # Ensure the channel belongs to the user and property
            channel = get_object_or_404(PropertyChannel, pk=channel_id, property_id=property_id, property__created_by__in=get_visible_user_ids(request.user))
            channel_name = channel.channel_type.name
            channel.delete()
            
            return JsonResponse({'success': True, 'message': f"Channel '{channel_name}' deleted successfully."})
        except PropertyChannel.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Channel not found.'}, status=404)
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

class WebsiteIndexView(TemplateView):
    template_name = 'frontend/website/index.html'

class WebsiteBlogView(TemplateView):
    template_name = 'frontend/website/blog.html'

class WebsiteBlogDetailsView(TemplateView):
    def get(self, request, slug, *args, **kwargs):
        # You can update the slug strings below to match your actual blog post slugs.
        if slug == 'the-risks-of-manual-management':
            self.template_name = 'frontend/website/blog-details1.html'
        elif slug == 'the-secret-to-scaling-your-rental-business':   
            self.template_name = 'frontend/website/blog-details2.html'
        elif slug == 'how-to-run-homestay-business-tips-and-tricks':
            self.template_name = 'frontend/website/blog-details3.html'
        elif slug == 'how-to-find-the-right-properties-for-the-short-term-rental-business':
            self.template_name = 'frontend/website/blog-details4.html'
        elif slug == 'how-to-increase-your-visibility-and-ranking-on-booking-com':
            self.template_name = 'frontend/website/blog-details5.html'
        elif slug == 'how-to-increase-your-visibility-and-ranking-on-airbnb':
            self.template_name = 'frontend/website/blog-details6.html'
        else:
            self.template_name = 'frontend/website/blog-details1.html'
            
        return self.render_to_response(self.get_context_data(slug=slug, **kwargs))


class WebsiteContactView(TemplateView):
    template_name = 'frontend/website/contact.html'

class WebsiteTermsView(TemplateView):
    template_name = 'frontend/website/Terms&Conditions.html'

class WebsitePrivacyView(TemplateView):
    template_name = 'frontend/website/privacy-policy.html'

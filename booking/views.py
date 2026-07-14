
import os
import re
from django.core.files import File
from django.views.generic import ListView, View
from .models import *
from property.models import Property, PropertyBlockDate
from shared.models import CountryAndState
from django.urls import reverse_lazy
from django.db import transaction
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.utils import timezone, dateparse
from django.db.models import Q, Value
from django.db.models.functions import Concat
from calendar import monthrange
from datetime import datetime, timedelta
from django.contrib.auth.mixins import LoginRequiredMixin
from accounts.utils import get_visible_user_ids, get_effective_user
from accounts import currency
from .enums import BOOKING_CHANNELS
from .utils import generate_booking_payments
from accounts.utils import get_visible_user_ids
from tasks.models import Task
from property.models import PropertyBlockDate

from django.core.mail import send_mail
from django.conf import settings

class BookingListView(LoginRequiredMixin, ListView):
    model = Booking
    template_name = 'frontend/booking/list.html'
    context_object_name = 'bookings'
    paginate_by = 12

    # Printable reports — one per reservation status. Each entry drives a
    # separate report document (title + subtitle) behind the Print button.
    REPORT_STATUSES = {
        'past':      {'title': 'Past Reservations',      'info': 'Completed stays'},
        'current':   {'title': 'Current Hosting',        'info': 'Guests currently checked in'},
        'upcoming':  {'title': 'Upcoming Reservations',  'info': 'Confirmed future arrivals'},
        'cancelled': {'title': 'Cancelled Reservations', 'info': 'Reservations that were cancelled'},
        'no_show':   {'title': 'No-Show Reservations',   'info': 'Guests who did not check in'},
    }

    # Image extensions that can be embedded inline in the printable report;
    # anything else (PDF, docx, …) is shown as a "see attached file" note.
    _REPORT_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg')

    @staticmethod
    def _status_queryset(base_qs, status_filter, now):
        """Apply the status filter + ordering shared by the list and reports."""
        if status_filter == 'past':
            # List sorted by checkout date, latest checkout on the top
            return base_qs.filter(check_out_date__lt=now, status='confirmed').order_by('-check_out_date')
        elif status_filter == 'current':
            # List sorted by Checkin Date, latest checking date on the top
            return base_qs.filter(check_in_date__lte=now, check_out_date__gte=now, status='confirmed').order_by('-check_in_date')
        elif status_filter == 'upcoming':
            # List sorted by Checkin Date, Closest checking date on the top
            return base_qs.filter(check_in_date__gt=now, status='confirmed').order_by('check_in_date')
        elif status_filter == 'cancelled':
            return base_qs.filter(status='cancelled').order_by('-created_at')
        elif status_filter == 'no_show':
            return base_qs.filter(status='no_show').order_by('-check_in_date')
        # 'all'
        return base_qs.order_by('-check_in_date')

    def get(self, request, *args, **kwargs):
        # Printable report ("Print Report" dropdown in the header): a branded,
        # print-ready document for a single reservation status.
        report_status = request.GET.get('report')
        if report_status:
            return self._render_report(request, report_status)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        status_filter = self.request.GET.get('status', 'current')
        # Use user's local timezone instead of UTC
        now = self.request.user.get_local_date()

        # Base queryset for the logged-in user
        base_qs = Booking.objects.filter(property__created_by__in=get_visible_user_ids(self.request.user)).select_related('property', 'channel').prefetch_related('images')

        property_id = self.request.GET.get('property_id')
        current_property = None
        if property_id:
            base_qs = base_qs.filter(property_id=property_id)
            current_property = Property.objects.filter(id=property_id, created_by__in=get_visible_user_ids(self.request.user)).first()

        # Calculate counts for all statuses
        now = self.request.user.get_local_date()

        bookings = self._status_queryset(base_qs, status_filter, now)

        search_query = self.request.GET.get('search', '')

        if search_query:
            # Annotate with full_name for searching
            bookings = bookings.annotate(
                full_name=Concat('first_name', Value(' '), 'last_name')
            )

            # Base query for text fields
            query = Q(full_name__icontains=search_query) | \
                    Q(email__icontains=search_query) | \
                    Q(phone__icontains=search_query) | \
                    Q(property__title__icontains=search_query) | \
                    Q(channel__name__icontains=search_query)

            # Add booking ID search if query is numeric
            if search_query.isdigit():
                query |= Q(booking_id=int(search_query))

            bookings = bookings.filter(query)

        # Paginate the queryset
        paginator = self.get_paginator(bookings, self.paginate_by)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # Order and serialize the data
        data = []
        for booking in page_obj.object_list:
            guest_image = booking.images.first()

            relevant_info = ''
            time_delta = False
            no_show_receipt = False
            urgency = 'green'
            if booking.status == 'cancelled':
                relevant_info = 'Cancelled'
                urgency = 'red'
            elif booking.status == 'no_show':
                relevant_info = 'No Show'
                urgency = 'amber'
                # No show receipt is available only from the checkout date onwards
                if booking.check_out_date and booking.check_out_date <= now:
                    no_show_receipt = True
            elif status_filter == 'upcoming':
                if booking.check_in_date:
                    delta = booking.check_in_date - now
                    if delta.days > 1:
                        relevant_info = f"Checkin in {delta.days} days"
                    elif delta.days == 1:
                        relevant_info = "Check-in tomorrow"
                    elif delta.days == 0:
                        relevant_info = "Check-in today"
            else:
                if booking.check_out_date:
                    delta = booking.check_out_date - now
                    if 0 <= delta.days <= 2:
                        urgency = 'amber'
                    if delta.days > 1:
                        relevant_info = f"Checkout in {delta.days} days"
                    elif delta.days == 1:
                        relevant_info = "Checkout tomorrow"
                    elif delta.days == 0:
                        relevant_info = "Checkout today"
                        time_delta = True
                    elif delta.days == -1:
                        relevant_info = "Checked out yesterday"
                    else:
                        days_ago = abs(delta.days)
                        relevant_info = f"Checked out {days_ago} days ago"
            data.append({
                'id': str(booking.id),
                'guest_name': f"{booking.first_name} {booking.last_name}",
                'property_name': booking.property.title,
                'is_checkin_today': bool(booking.check_in_date and booking.check_in_date == now and booking.status == 'confirmed'),
                'check_in': booking.check_in_date.strftime('%b %d, %Y') if booking.check_in_date else 'N/A',
                'check_out': booking.check_out_date.strftime('%b %d, %Y') if booking.check_out_date else 'N/A',
                'nights': booking.total_nights,
                'guests': booking.guest_count,
                'reservation_number': booking.booking_id,
                'total_price': currency.money(booking.price, self.request.user.currency),
                'platform': booking.channel.name if booking.channel else 'Others',
                'platform_icon': booking.channel.icon.url if booking.channel and booking.channel.icon else '',
                'guest_avatar': guest_image.image.url if guest_image else '/static/img/common/default_user_icon.png',
                'property_thumbnail': booking.property.get_primary_image_url() or '/static/img/property/placeholder-image.png',
                'due_status': 'Paid', # Placeholder
                'checkout_info': relevant_info,
                'time_delta': time_delta,
                'no_show_receipt': no_show_receipt,
                'urgency': urgency,
                'email': booking.email,
                'phone': booking.phone,
            })

        # Manually construct the context. This avoids calling super() with a
        # paginated list (which causes errors) and also avoids setting
        # self.paginate_by = None (which can hide template pagination controls).
        context = {
            'paginator': paginator,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'bookings': data,  # As defined by context_object_name
            'object_list': data,
            'view': self,
            'all': base_qs.count(),
            'past': base_qs.filter(check_out_date__lt=now, status='confirmed').count(),
            'current': base_qs.filter(check_in_date__lte=now, check_out_date__gte=now, status='confirmed').count(),
            'upcoming': base_qs.filter(check_in_date__gt=now, status='confirmed').count(),
            'cancelled': base_qs.filter(status='cancelled').count(),
            'no_show': base_qs.filter(status='no_show').count(),
            'status_filter': status_filter,
            'search_query': search_query,
            'current_property': current_property,
            'today_date': now,
        }
        return context

    def _booking_info(self, booking, status_filter, now):
        """Short human status line for a single booking in a report row."""
        if booking.status == 'cancelled':
            return 'Cancelled'
        if booking.status == 'no_show':
            return 'No Show'
        if status_filter == 'upcoming' and booking.check_in_date:
            delta = (booking.check_in_date - now).days
            if delta > 1:
                return f'Check-in in {delta} days'
            if delta == 1:
                return 'Check-in tomorrow'
            if delta == 0:
                return 'Check-in today'
        if status_filter == 'current':
            return 'Currently hosting'
        if booking.check_out_date:
            delta = (booking.check_out_date - now).days
            if delta > 1:
                return f'Checkout in {delta} days'
            if delta == 1:
                return 'Checkout tomorrow'
            if delta == 0:
                return 'Checkout today'
            if delta == -1:
                return 'Checked out yesterday'
            return f'Checked out {abs(delta)} days ago'
        return ''

    def _render_report(self, request, status_filter):
        """Render the branded, print-ready report for one reservation status.

        There is a distinct report per status (Past / Current / Upcoming /
        Cancelled / No-Show); the header dropdown links to each one. The report
        respects the property filter currently in view so it can be scoped to a
        single listing. UI mirrors the Revenue / Accounting report documents.
        """
        if status_filter not in self.REPORT_STATUSES:
            status_filter = 'current'
        meta = self.REPORT_STATUSES[status_filter]

        now = request.user.get_local_date()
        user_ids = get_visible_user_ids(request.user)
        base_qs = (
            Booking.objects
            .filter(property__created_by__in=user_ids)
            .select_related('property', 'channel')
            .prefetch_related('images', 'documents')
        )

        current_property = None
        property_id = request.GET.get('property_id')
        if property_id:
            base_qs = base_qs.filter(property_id=property_id)
            current_property = Property.objects.filter(id=property_id, created_by__in=user_ids).first()

        bookings = self._status_queryset(base_qs, status_filter, now)

        items = []
        attachment_count = 0
        total_nights = 0
        total_guests = 0
        total_value = 0.0
        for b in bookings:
            nights = b.total_nights or 0
            total_nights += nights
            total_guests += (b.guest_count or 0)
            total_value += float(b.price or 0)
            guest_name = f'{b.first_name} {b.last_name}'.strip() or '—'

            # Count of the guest's attachments (one guest photo + any uploaded
            # documents) — shown as a per-reservation count in the table and in
            # the totals. The photos/documents appendix itself was removed.
            has_photo = any(img.image and img.image.name for img in b.images.all())
            document_count = sum(
                1 for doc in b.documents.all() if doc.document and doc.document.name
            )
            group_count = (1 if has_photo else 0) + document_count
            attachment_count += group_count

            items.append({
                'reservation_number': b.booking_id,
                'guest_name': guest_name,
                'property_name': b.property.title if b.property else '—',
                'check_in': b.check_in_date,
                'check_out': b.check_out_date,
                'nights': nights,
                'guests': b.guest_count or 0,
                'channel': b.channel.name if b.channel else 'Others',
                'info': self._booking_info(b, status_filter, now),
                'price': b.price or 0,
                'attachment_count': group_count,
            })

        code = (getattr(request.user, 'currency', None) or currency.BASE_CURRENCY).upper()
        context = {
            'status_filter': status_filter,
            'report_title': meta['title'],
            'report_info': meta['info'],
            'account_name': request.user.get_full_name() or request.user.email,
            'generated_at': timezone.localtime(),
            'display_currency': code,
            'currency_symbol': currency.symbol_for(code),
            'current_property': current_property,
            'today_date': now,
            'items': items,
            'attachment_count': attachment_count,
            'reservation_count': len(items),
            'total_nights': total_nights,
            'total_guests': total_guests,
            'total_value': total_value,
        }
        return render(request, 'frontend/booking/reservation_report.html', context)

class BookingCreateView(LoginRequiredMixin, View):
    template_name = 'frontend/booking/create.html'

    def dispatch(self, request, *args, **kwargs):
        # Reservations can only be created once the host's profile is complete.
        # Blocks direct-URL access too, not just the "Create Reservation" button
        # (which shows the complete-profile modal). Uses the effective user so
        # co-hosts are gated by the host's profile.
        if request.user.is_authenticated and not get_effective_user(request.user).is_profile_complete():
            messages.error(request, 'Please complete your profile before creating a reservation.')
            return redirect('profile')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Get query parameters
        property_id = request.GET.get('property_id')
        check_in = request.GET.get('check_in')
        check_out = request.GET.get('check_out')
        guests = request.GET.get('guests')
        enquiry_id = request.GET.get('enquiry_id')

        form_data = {}
        if enquiry_id:
            enquiry = get_object_or_404(Enquiry, unique_id=enquiry_id, property__created_by__in=get_visible_user_ids(request.user))
            property_id = enquiry.property_id
            check_in_val = enquiry.check_in_date.strftime('%Y-%m-%d') if enquiry.check_in_date else None
            check_out_val = enquiry.check_out_date.strftime('%Y-%m-%d') if enquiry.check_out_date else None
            guests_val = enquiry.adults
            # guests_val = enquiry.adults + enquiry.children

            form_data = {
                'first_name': enquiry.first_name,
                'last_name': enquiry.last_name,
                'email': enquiry.email,
                'phone': enquiry.phone,
                'guest_count': guests_val,
                'notes': enquiry.notes_for_host,
                'property': property_id,
                'check_in_date': check_in_val,
                'check_out_date': check_out_val,
                'country_code': enquiry.country_code,
            }
            # Ensure individual context variables are updated to match enquiry data
            check_in, check_out, guests = check_in_val, check_out_val, guests_val
            enquiry_images = enquiry.images.all()
            enquiry_documents = enquiry.documents.all()
        else:
            enquiry_images = None
            enquiry_documents = None

        all_properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active').order_by('title')

        context = {
            'channels': BookingChannel.objects.all(),
            'property_id': property_id,
            'check_in_date': check_in,
            'check_out_date': check_out,
            'guest_count': guests,
            'all_properties': all_properties,
            'form_data': form_data,
            'enquiry_id': enquiry_id,
            'enquiry_images': enquiry_images,
            'enquiry_documents': enquiry_documents,
            'countries': CountryAndState.objects.order_by('country_name').values_list('country_name', flat=True).distinct(),
        }

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        try:
            enquiry_id = request.POST.get('enquiry_id')
            property_id = request.POST.get('property')
            check_in_str = request.POST.get('check_in_date')
            check_out_str = request.POST.get('check_out_date')

            if not all([property_id, check_in_str, check_out_str]):
                messages.error(request, "Property, check-in date, and check-out date are required.")
                # Re-render form with submitted data
                context = {
                    'channels': BookingChannel.objects.all(),
                    'all_properties': Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active').order_by('title'),
                    'form_data': request.POST,
                    'enquiry_id': enquiry_id,
                    'enquiry_images': EnquiryImage.objects.filter(enquiry__unique_id=enquiry_id) if enquiry_id else None,
                    'enquiry_documents': EnquiryDocument.objects.filter(enquiry__unique_id=enquiry_id) if enquiry_id else None,
                    'countries': CountryAndState.objects.order_by('country_name').values_list('country_name', flat=True).distinct(),
                }
                return render(request, self.template_name, context)

            phone = request.POST.get('phone')
            if phone:
                digits = re.sub(r'\D', '', phone)
                if len(digits) < 5:
                    messages.error(request, "Phone number must be at least 5 digits.")
                    context = {
                        'channels': BookingChannel.objects.all(),
                        'all_properties': Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active').order_by('title'),
                        'form_data': request.POST,
                        'enquiry_id': enquiry_id,
                        'enquiry_images': EnquiryImage.objects.filter(enquiry__unique_id=enquiry_id) if enquiry_id else None,
                        'enquiry_documents': EnquiryDocument.objects.filter(enquiry__unique_id=enquiry_id) if enquiry_id else None,
                        'countries': CountryAndState.objects.order_by('country_name').values_list('country_name', flat=True).distinct(),
                    }
                    return render(request, self.template_name, context)

            check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
            check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()

            with transaction.atomic():
                # Lock the property row to serialize booking creation for this property
                Property.objects.select_for_update().get(pk=property_id)

                # Check for conflicting confirmed bookings
                is_booked = Booking.objects.filter(
                    property_id=property_id,
                    status='confirmed',
                    check_in_date__lt=check_out_date,
                    check_out_date__gt=check_in_date
                ).exists()

                if is_booked:
                    raise Exception("The selected property is already booked for these dates. Please choose different dates or another property.")

                # Check for blocked dates
                is_blocked = PropertyBlockDate.objects.filter(
                    property_id=property_id,
                    is_active=True,
                    start_date__lt=check_out_date,
                    end_date__gt=check_in_date
                ).exists()

                if is_blocked:
                    raise Exception("The selected property is blocked for these dates. Please choose different dates or another property.")
                booking = Booking.objects.create(
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name'),
                    email=request.POST.get('email'),
                    phone=request.POST.get('phone'),
                    street_address=request.POST.get('street_address'),
                    city=request.POST.get('city'),
                    zip=request.POST.get('zip'),
                    country=request.POST.get('country'),
                    state=request.POST.get('state'),
                    nationality=request.POST.get('nationality'),
                    vehicle_information=request.POST.get('vehicle_information'),
                    country_code=request.POST.get('country_code'),
                    guest_count=int(request.POST.get('guest_count') or 0),
                    channel_id=request.POST.get('channel'),
                    property_id=request.POST.get('property'),
                    purpose_of_stay=request.POST.get('purpose_of_stay'),
                    check_in_date=datetime.strptime(request.POST.get('check_in_date'), '%Y-%m-%d').date() if request.POST.get('check_in_date') else None,
                    check_out_date=datetime.strptime(request.POST.get('check_out_date'), '%Y-%m-%d').date() if request.POST.get('check_out_date') else None,
                    check_in_time=request.POST.get('check_in_time'),
                    check_out_time=request.POST.get('check_out_time'),
                    notes=request.POST.get('notes'),
                    # Amounts are submitted in the host's display currency; store as USD.
                    price=currency.to_usd(request.POST.get('price', '0.00'), request.user.currency),
                    price_per_night=currency.to_usd(request.POST.get('price_per_night', '0.00'), request.user.currency),
                    deposit_fee=currency.to_usd(request.POST.get('deposit_fee', '0.00'), request.user.currency),
                    application_fee=currency.to_usd(request.POST.get('application_fee', '0.00'), request.user.currency),
                    taxes=currency.to_usd(request.POST.get('taxes', '0.00'), request.user.currency),
                    other_fees=currency.to_usd(request.POST.get('other_fees', '0.00'), request.user.currency),
                    cleaning_fee=currency.to_usd(request.POST.get('cleaning_fee', '0.00'), request.user.currency)

                )

                # --- Handle Guest Images ---
                for image_file in request.FILES.getlist('guest_images'):
                    GuestImage.objects.create(reservation=booking, image=image_file)

                # --- Handle Guest Attachments ---
                for doc_file in request.FILES.getlist('guest_attachments'):
                    GuestDocument.objects.create(reservation=booking, document=doc_file, name=doc_file.name, file_type=doc_file.content_type)

                # --- Map data from Enquiry if applicable ---
                if enquiry_id:
                    enquiry = Enquiry.objects.filter(unique_id=enquiry_id).first()
                    if enquiry:
                        # Copy Enquiry Images to Guest Images
                        for enq_img in enquiry.images.all():
                            # Create a new GuestImage by copying the file
                            guest_img = GuestImage(reservation=booking)
                            # Copy the file content
                            with enq_img.image.open() as src_file:
                                guest_img.image.save(
                                    os.path.basename(enq_img.image.name), 
                                    src_file, 
                                    save=True)

                        # Copy Enquiry Documents to Guest Documents
                        for enq_doc in enquiry.documents.all():
                            # Create a new GuestDocument by copying the file
                            guest_doc = GuestDocument(
                                reservation=booking,
                                name=enq_doc.name,
                                file_type=enq_doc.file_type
                            )
                            # Copy the file content
                            with enq_doc.document.open() as src_file:
                                guest_doc.document.save(
                                    os.path.basename(enq_doc.document.name), 
                                    src_file, 
                                    save=True)

                        # Archive the enquiry as it's now a reservation
                        # enquiry.is_archive = True
                        enquiry.is_booked = True
                        enquiry.reservation = booking
                        enquiry.updated_at = timezone.now()
                        enquiry.save()

                generate_booking_payments(booking)

            messages.success(request, "Reservation created successfully!")
            return redirect('booking:payment-details', pk=booking.pk)
        except Exception as e:
            print('Error==>',e.args[0])
            messages.error(request, f"An error occurred: {e}")
            return render(request, self.template_name, {
                'channels': BookingChannel.objects.all(),
                'countries': CountryAndState.objects.order_by('country_name').values_list('country_name', flat=True).distinct(),
            })


class BookingUpdateView(LoginRequiredMixin, View):
    template_name = 'frontend/booking/update.html'

    def get(self, request, *args, **kwargs):
        booking = get_object_or_404(Booking, pk=kwargs['pk'], property__created_by__in=get_visible_user_ids(request.user))
        
        # Find available properties for the booking's current dates/guests
        available_properties = []
        if booking.check_in_date and booking.check_out_date and booking.guest_count:
            # Find properties with overlapping confirmed bookings, excluding the current one
            overlapping_bookings = Booking.objects.filter(
                property__created_by__in=get_visible_user_ids(request.user),
                status='confirmed',
                check_in_date__lt=booking.check_out_date,
                check_out_date__gt=booking.check_in_date
            ).exclude(pk=booking.pk).values_list('property_id', flat=True)

            # Get properties that are not in the overlapping list and can accommodate the guests
            available_properties_qs = Property.objects.filter(
                created_by__in=get_visible_user_ids(request.user),
                guest__gte=booking.guest_count
            ).exclude(id__in=overlapping_bookings)
            available_properties = list(available_properties_qs)

        existing_images = booking.images.all()
        existing_attachments = booking.documents.all()
        channels = BookingChannel.objects.all()
        context = {
            'is_edit': True,
            'booking': booking,
            'available_properties': available_properties,
            'channels': channels,
            'existing_images': existing_images,
            'existing_attachments': existing_attachments,
            'countries': CountryAndState.objects.order_by('country_name').values_list('country_name', flat=True).distinct(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        booking = get_object_or_404(Booking, pk=kwargs['pk'], property__created_by__in=get_visible_user_ids(request.user))

        phone = request.POST.get('phone')
        if phone:
            digits = re.sub(r'\D', '', phone)
            if len(digits) < 5:
                messages.error(request, "Phone number must be at least 5 digits.")
                return redirect(request.META.get('HTTP_REFERER', reverse_lazy('booking:booking-edit', kwargs={'pk': booking.pk})))

        property_id = request.POST.get('property')
        check_in_str = request.POST.get('check_in_date')
        check_out_str = request.POST.get('check_out_date')

        check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()

        try:
            with transaction.atomic():
                # Lock the property row to serialize booking updates for this property
                Property.objects.select_for_update().get(pk=property_id)

                # Check for conflicting confirmed bookings, excluding the current one
                is_booked = Booking.objects.filter(
                    property_id=property_id,
                    status='confirmed',
                    check_in_date__lt=check_out_date,
                    check_out_date__gt=check_in_date
                ).exclude(pk=booking.pk).exists()

                if is_booked:
                    raise Exception("The selected property is already booked for these dates. Please choose different dates or another property.")

                # Check for blocked dates
                is_blocked = PropertyBlockDate.objects.filter(
                    property_id=property_id,
                    is_active=True,
                    start_date__lt=check_out_date,
                    end_date__gt=check_in_date
                ).exists()

                if is_blocked:
                    raise Exception("The selected property is blocked for these dates. Please choose different dates or another property.")
                old_check_in_date = booking.check_in_date
                old_check_out_date = booking.check_out_date
                # Snapshot fee/price values so we can detect fee-only edits and
                # regenerate the payment schedule for them too (not just date changes).
                old_price_values = (
                    booking.price_per_night, booking.cleaning_fee, booking.deposit_fee,
                    booking.taxes, booking.other_fees, booking.application_fee,
                )

                booking.first_name = request.POST.get('first_name')
                booking.last_name = request.POST.get('last_name')
                booking.email = request.POST.get('email')
                booking.phone = request.POST.get('phone')
                booking.street_address = request.POST.get('street_address')
                booking.city = request.POST.get('city')
                booking.zip = request.POST.get('zip')
                booking.country = request.POST.get('country')
                booking.state = request.POST.get('state')
                booking.nationality = request.POST.get('nationality')
                booking.vehicle_information = request.POST.get('vehicle_information')
                booking.country_code = request.POST.get('country_code')
                booking.guest_count = int(request.POST.get('guest_count') or 0)
                booking.channel_id = request.POST.get('channel')
                booking.property_id = request.POST.get('property')
                booking.purpose_of_stay = request.POST.get('purpose_of_stay')
                booking.check_in_date = datetime.strptime(request.POST.get('check_in_date'), '%Y-%m-%d').date() if request.POST.get('check_in_date') else None
                booking.check_out_date = datetime.strptime(request.POST.get('check_out_date'), '%Y-%m-%d').date() if request.POST.get('check_out_date') else None
                booking.check_in_time = request.POST.get('check_in_time')
                booking.check_out_time = request.POST.get('check_out_time')
                booking.notes = request.POST.get('notes')
                # Amounts are submitted in the host's display currency; store as USD.
                booking.price = currency.to_usd(request.POST.get('price', '0.00'), request.user.currency)
                booking.price_per_night = currency.to_usd(request.POST.get('price_per_night', '0.00'), request.user.currency)
                booking.cleaning_fee = currency.to_usd(request.POST.get('cleaning_fee', '0.00'), request.user.currency)
                booking.deposit_fee = currency.to_usd(request.POST.get('deposit_fee', '0.00'), request.user.currency)
                booking.taxes = currency.to_usd(request.POST.get('taxes', '0.00'), request.user.currency)
                booking.other_fees = currency.to_usd(request.POST.get('other_fees', '0.00'), request.user.currency)
                booking.application_fee = currency.to_usd(request.POST.get('application_fee', '0.00'), request.user.currency)
                booking.save()

                # --- Handle Guest Images ---
                for image_file in request.FILES.getlist('guest_images'):
                    GuestImage.objects.create(reservation=booking, image=image_file)

                # --- Handle Guest Attachments ---
                for doc_file in request.FILES.getlist('guest_attachments'):
                    GuestDocument.objects.create(reservation=booking, document=doc_file, name=doc_file.name, file_type=doc_file.content_type)

                # Regenerate the payment schedule when dates OR any fee/price
                # changed, so edits to Taxes, Other fees, etc. flow through to
                # the Payment Schedule for this reservation.
                new_price_values = (
                    booking.price_per_night, booking.cleaning_fee, booking.deposit_fee,
                    booking.taxes, booking.other_fees, booking.application_fee,
                )
                dates_changed = (old_check_in_date != booking.check_in_date or
                                 old_check_out_date != booking.check_out_date)
                if dates_changed or old_price_values != new_price_values:
                    # Delete old payment schedule and regenerate it
                    booking.payments.all().delete()
                    generate_booking_payments(booking)

            messages.success(request, "Reservation updated successfully!")
            return redirect('booking:payment-details', pk=booking.pk)
        except Exception as e:
            messages.error(request, f"An error occurred while updating the reservation: {e}")
            existing_images = booking.images.all()
            existing_attachments = booking.documents.all()
            channels = BookingChannel.objects.all()
            context = {'is_edit': True, 'booking': booking,
                       'channels': channels,
                       'existing_images': existing_images,
                       'existing_attachments': existing_attachments,
            }
            return render(request, self.template_name, context)





from django.views.decorators.http import require_POST
import json
from django.contrib.auth.decorators import login_required

@require_POST
def delete_guest_image(request):
    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        image = get_object_or_404(GuestImage, id=image_id, reservation__property__created_by__in=get_visible_user_ids(request.user))
        image.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@require_POST
def delete_guest_document(request):
    try:
        data = json.loads(request.body)
        document_id = data.get('document_id')
        document = get_object_or_404(GuestDocument, id=document_id, reservation__property__created_by__in=get_visible_user_ids(request.user))
        document.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
@login_required
def payment_details(request, pk):
    booking = get_object_or_404(Booking, pk=pk, property__created_by__in=get_visible_user_ids(request.user))
    payment_schedule = []
    subtotal = 0
    total_price = 0
    monthly_payment = 0
    nights = 0

    now = request.user.get_local_date()

    if booking.check_in_date and booking.check_out_date:
        nights = booking.total_nights
        subtotal = booking.price_per_night * nights

        payments = booking.payments.prefetch_related('attachments').all().order_by('pk')
        for payment in payments:
            payment_schedule.append({
                'id': payment.id,
                'name': payment.type,
                'amount': payment.amount,
                'date': payment.expected_payment_date,
                'is_paid': payment.is_paid,
                'notes': payment.notes or '',
                'attachments': [
                    {'id': a.id, 'url': a.file.url, 'name': a.name}
                    for a in payment.attachments.all().order_by('created_at')
                ],
            })
        
        if nights >= 30:
            monthly_payment = booking.price_per_night * 30
    
    # Total always uses the full stay rent (nights * daily rate), not just one
    # month's payment. The "Monthly Payment" line is informational only.
    total_price = subtotal + (booking.cleaning_fee or 0) + (booking.deposit_fee or 0) + (booking.taxes or 0) + (booking.other_fees or 0)

    # Determine booking status to conditionally show actions
    # now = timezone.now().date()
    booking_status = 'all' # default
    if booking.status == 'cancelled':
        booking_status = 'cancelled'
    elif booking.check_out_date and booking.check_out_date < now and booking.status == 'confirmed':
        booking_status = 'past'
    elif booking.check_in_date and booking.check_out_date and booking.check_in_date <= now and booking.check_out_date >= now and booking.status == 'confirmed':
        booking_status = 'current'
    elif booking.check_in_date and booking.check_in_date > now and booking.status == 'confirmed':
        booking_status = 'upcoming'

    is_checkin_today = bool(booking.check_in_date and booking.check_in_date == now and booking.status == 'confirmed')

    delta = (booking.check_out_date - now) if booking.check_out_date else None

    # No show receipt is available only from the checkout date onwards
    no_show_receipt = booking.status == 'no_show' and booking.check_out_date and booking.check_out_date <= now


    context = {
        'booking': booking,
        'nights': nights,
        'payment_schedule': payment_schedule,
        'subtotal': subtotal,
        'total_price': total_price,
        'monthly_payment': monthly_payment,
        'time_delta': True if (delta is not None and delta.days == 0) else False,
        'no_show_receipt': no_show_receipt,
        'is_checkin_today': is_checkin_today,
    }
    context['booking_status'] = booking_status

    if request.GET.get('partial'):
        return render(request, 'frontend/booking/payment_details_partial.html', context)

    return render(request, 'frontend/booking/payment_details.html', context)

@require_POST
def update_payment_status(request):
    try:
        data = json.loads(request.body)
        payment_id = data.get('payment_id')
        is_paid = data.get('is_paid')

        payment = get_object_or_404(Payment, id=payment_id, booking__property__created_by__in=get_visible_user_ids(request.user))
        payment.is_paid = is_paid
        payment.save()
        return JsonResponse({'success': True, 'message': 'Payment status updated.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@require_POST
@login_required
def add_payment_attachment(request):
    try:
        payment_id = request.POST.get('payment_id')
        file = request.FILES.get('attachment')
        if not file:
            return JsonResponse({'success': False, 'error': 'No file provided.'}, status=400)
        if file.size > 2 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File size must not exceed 2 MB.'}, status=400)

        payment = get_object_or_404(Payment, id=payment_id, booking__property__created_by__in=get_visible_user_ids(request.user))
        att = PaymentAttachment.objects.create(payment=payment, file=file, name=file.name)
        return JsonResponse({
            'success': True,
            'attachment': {'id': att.id, 'url': att.file.url, 'name': att.name},
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
@login_required
def delete_payment_attachment(request):
    try:
        data = json.loads(request.body)
        att_id = data.get('attachment_id')
        att = get_object_or_404(PaymentAttachment, id=att_id, payment__booking__property__created_by__in=get_visible_user_ids(request.user))
        att.file.delete(save=False)
        att.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
@login_required
def update_payment_notes(request):
    try:
        data = json.loads(request.body)
        payment_id = data.get('payment_id')
        notes = data.get('notes', '').strip()
        payment = get_object_or_404(Payment, id=payment_id, booking__property__created_by__in=get_visible_user_ids(request.user))
        payment.notes = notes
        payment.save()
        return JsonResponse({'success': True, 'notes': payment.notes or ''})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
def render_email_form(request):
    booking_id = request.GET.get('booking_id')
    try:
        booking = get_object_or_404(Booking, id=booking_id, property__created_by__in=get_visible_user_ids(request.user))
        nights = 0
        if booking.check_in_date and booking.check_out_date:
            nights = (booking.check_out_date - booking.check_in_date).days
        context = {
            'booking': booking,
            'nights': nights,
        }
        return render(request, 'frontend/common/send_email.html', context)
    except Exception as e:
        # In a real app, you might want to log this error.
        # Returning a simple error message to the modal.
        return HttpResponse(f"<p>Error: Could not load booking data. {e}</p>", status=404)


@require_POST
@login_required
def send_guest_email(request):
    try:
        booking_id = request.POST.get('booking_id')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        booking = get_object_or_404(Booking, id=booking_id, property__created_by__in=get_visible_user_ids(request.user))
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.email],
            fail_silently=False,
        )
        
        messages.success(request, f"Email successfully sent to {booking.first_name} {booking.last_name}.")
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('booking:booking-list')))
    except Exception as e:
        messages.error(request, f"Failed to send email. Error: {e}")
        return redirect(request.META.get('HTTP_REFERER', reverse_lazy('booking:booking-list')))




@login_required
def guest_receipt(request, pk):
    booking = get_object_or_404(Booking, pk=pk, property__created_by__in=get_visible_user_ids(request.user))

    # Check if the request is for a modal view
    is_modal = request.GET.get('is_modal') == 'true'
    
    nights = 0
    if booking.check_in_date and booking.check_out_date:
        nights = (booking.check_out_date - booking.check_in_date).days

    # Calculate totals. The refundable deposit is money held in trust, not
    # revenue, so it is excluded from the receipt's total, amount paid, and
    # balance. We do this by ignoring deposit-type payment rows entirely
    # rather than subtracting a fixed deposit figure.
    DEPOSIT_PAYMENT_TYPES = {'Refundable deposit', 'Refundable to guest'}
    payments = booking.payments.all()
    total_paid = sum(p.amount for p in payments if p.is_paid)
    paid_excluding_deposit = sum(
        p.amount for p in payments
        if p.is_paid and p.type not in DEPOSIT_PAYMENT_TYPES
    )
    subtotal = (booking.price_per_night or 0) * nights
    total_price = subtotal + (booking.cleaning_fee or 0) + (booking.taxes or 0) + (booking.other_fees or 0)
    all_paid = paid_excluding_deposit >= total_price

    balance_due = max(total_price - paid_excluding_deposit, 0)

    context = {
        'booking': booking,
        'nights': nights,
        'subtotal': subtotal,
        'total_paid': total_paid,
        'paid_excluding_deposit': paid_excluding_deposit,
        'total_price': total_price,
        'balance_due': balance_due,
        'all_paid': all_paid,
        'is_modal': is_modal,
    }
    return render(request, 'frontend/common/receipt.html', context)



class CancelBookingView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking_id = kwargs.get('pk')
        booking = get_object_or_404(Booking, pk=booking_id, property__created_by__in=get_visible_user_ids(request.user))

        # Prevent cancellation of bookings that are not upcoming
        # if booking.status != 'upcoming':
        #     return JsonResponse({'success': False, 'error': f'Only upcoming reservations can be cancelled. This reservation is {booking.status}.'}, status=400)

        try:
            with transaction.atomic():
                booking.status = 'cancelled'
                booking.updated_at = timezone.now()
                booking.save()

                booking.payments.all().delete()
            messages.success(request, "Booking cancelled successfully.")
            return JsonResponse({'success': True, 'message': 'Booking cancelled successfully.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class MarkNoShowView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking_id = kwargs.get('pk')
        booking = get_object_or_404(Booking, pk=booking_id, property__created_by__in=get_visible_user_ids(request.user))

        # Unlike cancellation, payments are kept as the money is not refunded
        try:
            with transaction.atomic():
                booking.status = 'no_show'
                booking.updated_at = timezone.now()
                booking.save()
            messages.success(request, "Booking marked as no show successfully.")
            return JsonResponse({'success': True, 'message': 'Booking marked as no show successfully.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


#Enquiry API Views
@require_POST
def enquiry_create_api(request):
    """API endpoint to create an Enquiry from the public request_book page."""
    try:
        property_id = request.POST.get('property_id')
        prop = get_object_or_404(Property, id=property_id)

        check_in_str = request.POST.get('check_in_date')
        check_out_str = request.POST.get('check_out_date')

        check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date() if check_in_str else None
        check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date() if check_out_str else None

        with transaction.atomic():
            enquiry = Enquiry.objects.create(
                property=prop,
                first_name=request.POST.get('first_name'),
                last_name=request.POST.get('last_name'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone'),
                country_code=request.POST.get('country_code'),
                phone_code=request.POST.get('phone_code'),
                notes_for_host=request.POST.get('notes'),
                adults=int(request.POST.get('adults', 1)),
                children=int(request.POST.get('children', 0)),
                pets=int(request.POST.get('pets', 0)),
                pet_details=request.POST.get('pet_details'),
                check_in_date=check_in_date,
                check_out_date=check_out_date,
            )

            # Handle guest photo (EnquiryImage)
            guest_photo = request.FILES.get('guest_photo')
            if guest_photo:
                EnquiryImage.objects.create(enquiry=enquiry, image=guest_photo)

            # Handle attachments (EnquiryDocument)
            attachments = request.FILES.getlist('attachments')
            for attachment in attachments:
                EnquiryDocument.objects.create(
                    enquiry=enquiry,
                    document=attachment,
                    name=attachment.name,
                    file_type=attachment.content_type
                )

        return JsonResponse({'success': True, 'enquiry_id': enquiry.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

class EnquiryListView(LoginRequiredMixin, ListView):
    model = Enquiry
    template_name = 'frontend/enquiry/list.html'
    context_object_name = 'enquiries'
    paginate_by = 12


    def get_context_data(self, **kwargs):
        status_filter = self.request.GET.get('status', 'new')
        search_query = self.request.GET.get('search', '')

        # Base queryset for the logged-in user
        enquiry_qs = Enquiry.objects.filter(
            property__created_by__in=get_visible_user_ids(self.request.user),
            ).select_related(
                'property'
            )

        if status_filter == 'new':
            enquiry = enquiry_qs.filter(is_archive=False,is_booked=False)
        elif status_filter == 'archive':
            enquiry = enquiry_qs.filter(is_archive=True)
        elif status_filter == 'reserved':
            enquiry = enquiry_qs.filter(is_booked=True)

        if search_query:
            # Annotate with full_name for searching
            enquiry = enquiry.annotate(
                full_name=Concat('first_name', Value(' '), 'last_name')
            )
            query = Q(full_name__icontains=search_query) | \
                    Q(email__icontains=search_query) | \
                    Q(phone__icontains=search_query) | \
                    Q(property__title__icontains=search_query)
            enquiry = enquiry.filter(query)

        # Paginate the queryset
        paginator = self.get_paginator(enquiry, self.paginate_by)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # Calculate derived fields for the template
        now = self.request.user.get_local_date()
        for item in page_obj.object_list:
            item.guest_count = item.adults + item.children
            item.days_until_checkin = (item.check_in_date - now).days if item.check_in_date else 0

            
        context = {
            'status_filter': status_filter,
            'paginator': paginator,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'enquiries': enquiry,
            'search_query': search_query,
            'new_enquiry': enquiry_qs.filter(is_archive=False, is_booked=False).count(),
            'archive_enquiry': enquiry_qs.filter(is_archive=True).count(),
            'total_reserved': enquiry_qs.filter(is_booked=True).count()
        }

        return context
    

class EnquiryDetailView(LoginRequiredMixin, View):
    template_name = 'frontend/enquiry/details.html'

    def get(self, request, *args, **kwargs):
        enquiry = get_object_or_404(Enquiry, unique_id=kwargs['unique_id'], property__created_by__in=get_visible_user_ids(request.user))

        # Financial calculations based on the associated property
        prop = enquiry.property
        nights = enquiry.total_nights

        price_per_night = prop.price_per_night or 0
        subtotal = price_per_night * nights
        cleaning_fee = prop.cleaning_fee or 0
        deposit_fee = prop.refundable_deposit or 0
        application_fee = prop.application_fees or 0

        monthly_payment = 0
        if nights >= 30:
            monthly_payment = price_per_night * 30
        # Total always uses the full stay rent (nights * daily rate), not just
        # one month's payment. The "Monthly Payment" line is informational only.
        total_price = subtotal + cleaning_fee + deposit_fee + application_fee

        context = {
            'enquiry': enquiry,
            'images': enquiry.images.all(),
            'documents': enquiry.documents.all(),
            'nights': nights,
            'subtotal': subtotal,
            'total_price': total_price,
            'monthly_payment': monthly_payment,
            'price_per_night': price_per_night,
            'cleaning_fee': cleaning_fee,
            'deposit_fee': deposit_fee,
            'application_fee': application_fee,
        }
        return render(request, self.template_name, context)

@require_POST
@login_required
def archive_enquiry_api(request, unique_id):
    """API endpoint to archive an Enquiry."""
    enquiry = get_object_or_404(Enquiry, unique_id=unique_id, property__created_by__in=get_visible_user_ids(request.user))
    enquiry.is_archive = True
    enquiry.save()
    return JsonResponse({'success': True, 'message': 'Enquiry archived successfully.'})

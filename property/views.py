from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json
from django.utils import timezone
from datetime import datetime, timedelta

from booking.models import Booking
from accounts.models import MyUser
from .models import Property, PropertyImage, PropertyDocument, Amenities, PropertyBlockDate
from icalendar import Calendar, Event
from django.http import HttpResponse

from .forms import PropertyForm
from django.db import transaction
from django.db.models import Q
from django.core.files import File
from django.contrib.auth.mixins import LoginRequiredMixin
from accounts.utils import get_visible_user_ids, get_effective_user



class PropertyCreateView(LoginRequiredMixin, CreateView):
    model = Property
    form_class = PropertyForm
    template_name = 'frontend/property/create.html'
    success_url = reverse_lazy('property:property-list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        clone_from_id = self.request.GET.get('clone_from')
        if clone_from_id:
            kwargs['clone_from_id'] = clone_from_id
        return kwargs

    def get_initial(self):
        from django.forms.models import model_to_dict
        initial = super().get_initial()
        clone_from_id = self.request.GET.get('clone_from')
        if clone_from_id:
            try:
                original_property = get_object_or_404(Property, pk=clone_from_id)
                initial = model_to_dict(original_property, exclude=['id', 'slug', 'amenities'])
                initial['title'] = f"{original_property.title} (copy)"
            except Property.DoesNotExist:
                pass
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['amenities'] = Amenities.objects.all()
        context['is_edit'] = False
        clone_from_id = self.request.GET.get('clone_from')
        context['is_clone'] = False
        context['selected_amenities'] = []
        if clone_from_id:
            original_property = get_object_or_404(Property, pk=clone_from_id)
            context['selected_amenities'] = list(original_property.amenities.values_list('id', flat=True))
            context['existing_images'] = original_property.images.all()
            all_docs = original_property.documents.all()
            context['existing_check_in_docs'] = all_docs.filter(document_type='check_in')
            context['existing_check_out_docs'] = all_docs.filter(document_type='check_out')
            context['is_clone'] = True
        return context
    
    def form_valid(self, form):
        # Assign the effective user (host if co-host) to the created_by field
        form.instance.created_by = get_effective_user(self.request.user)

        # Use transaction to ensure all operations succeed or none do
        with transaction.atomic():
            response = super().form_valid(form)
            
            # Handle amenities
            amenity_ids = self.request.POST.getlist('amenities')
            if amenity_ids:
                self.object.amenities.set(amenity_ids)
            
            # Handle new file uploads
            self.handle_file_uploads()

            # Handle cloning of existing files
            if self.request.GET.get('clone_from'):
                self.handle_cloned_files()
            
            messages.success(self.request, 'Property created successfully!')
            return response
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def handle_cloned_files(self):
        """
        Copies selected images and documents from an original property
        to the newly created one.
        """
        image_ids_to_clone = self.request.POST.getlist('clone_images')
        doc_ids_to_clone = self.request.POST.getlist('clone_documents')

        # Clone images
        for image_id in image_ids_to_clone:
            try:
                original_image = PropertyImage.objects.get(id=image_id)
                new_image_obj = PropertyImage(
                    property=self.object,
                    is_primary=original_image.is_primary
                )
                file_name = original_image.image.name.split('/')[-1]
                new_image_obj.image.save(file_name, File(original_image.image.file), save=True)
            except (PropertyImage.DoesNotExist, FileNotFoundError):
                continue
        
        # Clone documents
        for doc_id in doc_ids_to_clone:
            try:
                original_doc = PropertyDocument.objects.get(id=doc_id)
                new_doc_obj = PropertyDocument(
                    property=self.object,
                    name=original_doc.name,
                    file_type=original_doc.file_type
                )
                file_name = original_doc.document.name.split('/')[-1]
                new_doc_obj.document.save(file_name, File(original_doc.document.file), save=True)
            except (PropertyDocument.DoesNotExist, FileNotFoundError):
                continue
    
    def handle_file_uploads(self):
        """Handle property images and documents upload"""
        try:
            # Handle property images
            images = self.request.FILES.getlist('property_images')
            print(f"Received {len(images)} images")  # Debug
            
            for i, image in enumerate(images):
                PropertyImage.objects.create(
                    property=self.object,
                    image=image,
                    is_primary=(i == 0)  # First image is primary
                )
                print(f"Created image: {image.name}")  # Debug
            
            # Handle check-in documents
            checkin_docs = self.request.FILES.getlist('check_in_documents')
            for doc in checkin_docs:
                PropertyDocument.objects.create(
                    property=self.object,
                    document=doc,
                    name=doc.name,
                    file_type=doc.content_type,
                    document_type='check_in'
                )

            # Handle check-out documents
            checkout_docs = self.request.FILES.getlist('check_out_documents')
            for doc in checkout_docs:
                PropertyDocument.objects.create(
                    property=self.object,
                    document=doc,
                    name=doc.name,
                    file_type=doc.content_type,
                    document_type='check_out'
                )
                
        except Exception as e:
            print(f"Error handling file uploads: {e}")  # Debug
            messages.error(self.request, f'Error uploading files: {str(e)}')
            raise

    def post(self, request, *args, **kwargs):
        """Override post to debug file uploads"""
        print("POST data keys:", list(request.POST.keys()))  # Debug
        print("FILES data keys:", list(request.FILES.keys()))  # Debug
        print("property_images count:", len(request.FILES.getlist('property_images')))  # Debug
        print("check_in_documents count:", len(request.FILES.getlist('check_in_documents')))
        print("check_out_documents count:", len(request.FILES.getlist('check_out_documents')))
        
        return super().post(request, *args, **kwargs)

class PropertyEditView(LoginRequiredMixin, UpdateView):
    model = Property
    form_class = PropertyForm
    template_name = 'frontend/property/create.html'
    context_object_name = 'property'
    
    def get_success_url(self):
        # return reverse_lazy('property:property-list')
        return reverse_lazy('property:property-detail', kwargs={'slug': self.object.slug})
    
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['amenities'] = Amenities.objects.all()
        context['is_edit'] = True
        context['existing_images'] = self.object.images.all()
        all_docs = self.object.documents.all()
        context['existing_check_in_docs'] = all_docs.filter(document_type='check_in')
        context['existing_check_out_docs'] = all_docs.filter(document_type='check_out')
        context['selected_amenities'] = list(self.object.amenities.values_list('id', flat=True))
        return context
    
    def form_valid(self, form):
        try:
            # Print cleaned form data
            print("===== FORM CLEANED DATA =====")
            for field, value in form.cleaned_data.items():
                print(f"{field}: {value}")

            # Print raw POST data
            print("===== RAW POST DATA =====")
            for key, value in self.request.POST.items():
                print(f"{key}: {value}")

            # Print uploaded files
            print("===== FILES =====")
            for key, file in self.request.FILES.items():
                print(f"{key}: {file.name} ({file.content_type}, {file.size} bytes)")


            
            response = super().form_valid(form)
            
            # Handle amenities
            amenity_ids = self.request.POST.getlist('amenities')
            self.object.amenities.set(amenity_ids if amenity_ids else [])
            
            # Handle file uploads
            self.handle_file_uploads()
            
            messages.success(self.request, 'Property updated successfully!')
            return response
        except Exception as e:
            messages.error(self.request, f"Unexpected error: {e}")
            raise   # re-raise so you can see full traceback in debug
    
    def form_invalid(self, form):
        print("===== FORM ERRORS =====")
        print(form.errors)

        print("===== RAW POST DATA =====")
        for key, value in self.request.POST.items():
            print(f"{key}: {value}")

        print("===== FILES =====")
        for key, file in self.request.FILES.items():
            print(f"{key}: {file.name} ({file.content_type}, {file.size} bytes)")

        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)
    
    def handle_file_uploads(self):
        # Handle new property images
        images = self.request.FILES.getlist('property_images')
        for i, image in enumerate(images):
            # Check if this is the first image and no primary exists
            has_primary = self.object.images.filter(is_primary=True).exists()
            PropertyImage.objects.create(
                property=self.object,
                image=image,
                is_primary=(not has_primary and i == 0)
            )
        
        # Handle check-in documents
        checkin_docs = self.request.FILES.getlist('check_in_documents')
        for doc in checkin_docs:
            PropertyDocument.objects.create(
                property=self.object,
                document=doc,
                name=doc.name,
                file_type=doc.content_type,
                document_type='check_in'
            )

        # Handle check-out documents
        checkout_docs = self.request.FILES.getlist('check_out_documents')
        for doc in checkout_docs:
            PropertyDocument.objects.create(
                property=self.object,
                document=doc,
                name=doc.name,
                file_type=doc.content_type,
                document_type='check_out'
            )

class PropertyDeleteView(LoginRequiredMixin,DeleteView):
    model = Property
    success_url = reverse_lazy('property:property-list')

    def get_queryset(self):
        return Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user))

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        today = timezone.now().date()

        # Check for active or future reservations
        has_active_reservations = Booking.objects.filter(
            property=self.object,
            check_out_date__gte=today,
        ).exclude(status='cancelled').exists()

        if has_active_reservations:
            referer_url = request.META.get('HTTP_REFERER', self.get_success_url())
            messages.error(request, 'This property cannot be deleted because it has active or future reservations.')
            return redirect(referer_url)
        
        messages.success(self.request, 'Property deleted successfully!')
        return self.delete(request, *args, **kwargs)

class PropertyListView(LoginRequiredMixin, ListView):
    model = Property
    template_name = 'frontend/property/list.html'
    context_object_name = 'properties'
    paginate_by = 20
    
    def get_queryset(self):
        # queryset = Property.objects.prefetch_related('images', 'amenities').all()
        queryset = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user)).prefetch_related('images').all()
        
        # Search functionality
        search_query = self.request.GET.get('search', '').strip()
        # print("search_query==>",search_query)
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(city__icontains=search_query) |
                Q(state__icontains=search_query) |
                Q(country__icontains=search_query)
            )
        
        # Filter by check-in/check-out dates (basic implementation)
        check_in = self.request.GET.get('check_in')
        check_out = self.request.GET.get('check_out')

        nights = 0
        
        guests = self.request.GET.get('guests')

        if check_in or check_out or guests:
            queryset = queryset.filter(status='Active')

        if check_in and check_out:
            try:
                check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
                check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()

                if check_out_date > check_in_date:
                    # Calculate nights and filter by minimum booking
                    nights = (check_out_date - check_in_date).days
                    queryset = queryset.filter(minimum_booking__lte=nights)

                    # Exclude properties with overlapping bookings
                    overlapping_bookings = Booking.objects.filter(
                        check_in_date__lt=check_out_date,
                        check_out_date__gt=check_in_date,
                        status='confirmed'  # Only consider confirmed bookings
                    )
                    properties_with_bookings = overlapping_bookings.values_list('property_id', flat=True)
                    queryset = queryset.exclude(id__in=properties_with_bookings)

                    # Exclude properties with overlapping block dates
                    overlapping_blocks = PropertyBlockDate.objects.filter(
                        is_active=True,
                        start_date__lt=check_out_date,
                        end_date__gt=check_in_date
                    )
                    properties_with_blocks = overlapping_blocks.values_list('property_id', flat=True)
                    queryset = queryset.exclude(id__in=properties_with_blocks)
            except (ValueError, TypeError):
                pass # Ignore if dates are invalid

        if guests:
            try:
                guest_count = int(guests)
                queryset = queryset.filter(guest__gte=guest_count)
            except (ValueError, TypeError):
                pass

        return queryset.order_by('title')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        properties_on_page = context['object_list']
        check_in = self.request.GET.get('check_in', '')
        check_out = self.request.GET.get('check_out', '')

        context['search_query'] = self.request.GET.get('search', '')
        context['check_in'] = check_in
        context['check_out'] = check_out
        context['guests'] = self.request.GET.get('guests', '')
        context['total_listing'] = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user)).count()
        context['is_profile_complete'] = self.request.user.is_profile_complete()
        return context

class PropertyDetailView(LoginRequiredMixin, DetailView):
    model = Property
    template_name = 'frontend/property/detail.html'
    context_object_name = 'property'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_documents = self.object.documents.all()
        context['images'] = self.object.images.all()
        # context['documents'] = self.object.documents.all()
        context['amenities'] = self.object.amenities.all().order_by('name')
        context['check_in_docs'] = all_documents.filter(document_type='check_in')
        context['check_out_docs'] = all_documents.filter(document_type='check_out')
        return context

# AJAX Views for file management
@method_decorator(csrf_exempt, name='dispatch')
class DeleteImageView(DeleteView):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            image_id = data.get('image_id')
            image = get_object_or_404(PropertyImage, id=image_id)
            image.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

@method_decorator(csrf_exempt, name='dispatch')
class DeleteDocumentView(DeleteView):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            doc_id = data.get('document_id')
            document = get_object_or_404(PropertyDocument, id=doc_id)
            document.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

from django.views.generic import View
class PropertyToggleStatusView(View):
    success_url = reverse_lazy('property:property-list')

    def post(self, request, pk, *args, **kwargs):
        property_obj = get_object_or_404(Property, pk=pk, created_by__in=get_visible_user_ids(request.user))
        referer_url = request.META.get('HTTP_REFERER', self.success_url)
        new_status = "Inactive" if property_obj.status == "Active" else "Active"

        # If trying to set to Inactive, check for reservations
        if new_status == "Inactive":
            today = timezone.now().date()
            has_active_reservations = Booking.objects.filter(
                property=property_obj,
                check_out_date__gte=today
            ).exclude(status='cancelled').exists()
            if has_active_reservations:
                messages.error(request, 'This property cannot be made inactive because it has active or future reservations.')
                return redirect(referer_url)

        property_obj.status = new_status
        property_obj.save()

        messages.success(request, f'Property status updated to {new_status}.')
        return redirect(referer_url)

def check_property_availability(request, pk):
    property_obj = get_object_or_404(Property, pk=pk)
    check_in_str = request.GET.get('check_in')
    check_out_str = request.GET.get('check_out')
    guests_str = request.GET.get('guests')
    booking_id_to_exclude = request.GET.get('booking_id')

    if not all([check_in_str, check_out_str, guests_str]):
        return JsonResponse({'available': False, 'error': 'Check-in, check-out, and guest count are required.'}, status=400)

    try:
        guests = int(guests_str)
        if guests > property_obj.guest:
            return JsonResponse({'available': False})

        check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()
        
        # Calculate the number of nights
        num_nights = (check_out_date - check_in_date).days

        # Check if the number of nights is less than the minimum allowed
        if num_nights < property_obj.minimum_booking:
            return JsonResponse({'available': False, 'error': f'Minimum {property_obj.minimum_booking} nights required.'}, status=400)

    except (ValueError, TypeError) as e:
        return JsonResponse({'available': False, 'error': 'Invalid date or guest format.'}, status=400)
    conflict_query = Booking.objects.filter(
        property=property_obj,
        check_in_date__lt=check_out_date,
        check_out_date__gt=check_in_date,
        status='confirmed'
    )
    if booking_id_to_exclude:
        conflict_query = conflict_query.exclude(id=booking_id_to_exclude)

    # Check for blocked dates
    is_blocked = PropertyBlockDate.objects.filter(
        property=property_obj,
        start_date__lt=check_out_date,
        end_date__gt=check_in_date
    ).exists()

    is_booked = conflict_query.exists() or is_blocked

    print('booked =>', is_booked)

    if is_booked:
        return JsonResponse({'available': False})

    return JsonResponse({'available': True})

class AvailablePropertiesAjaxView(LoginRequiredMixin, View):
    """
    Returns a list of available properties based on check-in, check-out,
    and guest count.
    """
    def get(self, request, *args, **kwargs):
        check_in_str = request.GET.get('check_in')
        check_out_str = request.GET.get('check_out')
        guests_str = request.GET.get('guests')
        booking_id_to_exclude = request.GET.get('booking_id')

        all_properties = Property.objects.filter(created_by__in=get_visible_user_ids(request.user), status='Active')
        properties_data = []

        # If dates and guests are provided, check availability
        check_in_date, check_out_date, guests, nights = None, None, None, None

        if check_in_str and check_out_str:
            try:
                check_in_date = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                check_out_date = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                nights = (check_out_date - check_in_date).days
            except (ValueError, TypeError): 
                pass

        if guests_str:
            try:
                guests = int(guests_str)
            except (ValueError, TypeError):
                pass

        for p in all_properties:
            # Default to available unless all conditions for a check are met.
            is_available = True 

            # Check guest count if provided
            if guests and guests > 0:
                is_available = p.guest >= guests

            # If guest count is okay, and dates are provided, check booking conflicts.
            if is_available and check_in_date and check_out_date and check_out_date > check_in_date:
                is_nights_ok = p.minimum_booking <= nights
                
                conflict_query = Booking.objects.filter(
                    property=p,
                    status='confirmed',
                    check_in_date__lt=check_out_date,  # An existing booking starts before the new one ends.
                    check_out_date__gt=check_in_date   # An existing booking ends after the new one starts.
                )
                if booking_id_to_exclude:
                    conflict_query = conflict_query.exclude(id=booking_id_to_exclude)
                
                # Check for blocked dates
                is_blocked_date = PropertyBlockDate.objects.filter(
                    property=p,
                    start_date__lt=check_out_date,
                    end_date__gt=check_in_date
                ).exists()

                is_not_booked = not conflict_query.exists()
                is_available = is_nights_ok and is_not_booked and not is_blocked_date

            properties_data.append({
                'id': str(p.id),
                'title': p.title,
                'image_url': p.get_primary_image_url(),
                'location': p.location_display(),
                'price_per_night': p.price_per_night,
                'cleaning_fee': p.cleaning_fee,
                'refundable_deposit': p.refundable_deposit,
                'application_fees': p.application_fees,
                'guest': p.guest,
                'minimum_nights': p.minimum_booking,
                'is_available': is_available
            })
            
        return JsonResponse({'properties': properties_data})

def export_property_ical(request, pk):
    """
    Generates an iCalendar (.ics) file for a property's bookings.
    """
    # Find the property by its ID and verify the token
    token = request.GET.get('t')
    property_obj = get_object_or_404(Property, pk=pk, ical_token=token)

    # Create a new calendar
    cal = Calendar()
    cal.add('prodid', f'-//Bookaid//Property {property_obj.id}//EN')
    cal.add('version', '2.0')
    cal.add('name', property_obj.title)
    cal.add('X-WR-CALNAME', property_obj.title)

    # Get all confirmed bookings for this property
    bookings = Booking.objects.filter(property=property_obj).exclude(status='cancelled')

    for booking in bookings:
        event = Event()
        event.add('summary', f"Reserved - {booking.first_name or 'Guest'}")
        event.add('dtstart', booking.check_in_date)
        event.add('dtend', booking.check_out_date)
        event.add('dtstamp', booking.created_at)
        event.add('uid', booking.external_uid or f"{booking.id}-{property_obj.id}@favhost.com")
        cal.add_component(event)

    # Get all active blocked dates for this property
    blocked_dates = PropertyBlockDate.objects.filter(property=property_obj, is_active=True)

    for block in blocked_dates:
        event = Event()
        event.add('summary', 'Blocked')
        event.add('dtstart', block.start_date)
        event.add('dtend', block.end_date)
        event.add('dtstamp', block.created_at)
        event.add('uid', block.external_uid or f"{block.id}-{property_obj.id}@favhost.com")
        cal.add_component(event)

    response = HttpResponse(cal.to_ical(), content_type="text/calendar")
    response['Content-Disposition'] = f'attachment; filename="{property_obj.slug}.ics"'
    return response

@method_decorator(csrf_exempt, name='dispatch')
class BlockPropertyDateView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            property_id = data.get('property_id')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            
            if not all([property_id, start_date, end_date]):
                return JsonResponse({'success': False, 'error': 'Missing required fields'})

            property_obj = get_object_or_404(Property, id=property_id)
            
            # Check for overlapping confirmed bookings
            if Booking.objects.filter(
                property=property_obj,
                status='confirmed',
                check_in_date__lt=end_date,
                check_out_date__gt=start_date
            ).exists():
                return JsonResponse({'success': False, 'error': 'Cannot block dates overlapping with an existing reservation.'})

            # Check for overlapping existing blocks
            if PropertyBlockDate.objects.filter(
                property=property_obj,
                is_active=True,
                start_date__lt=end_date,
                end_date__gt=start_date
            ).exists():
                return JsonResponse({'success': False, 'error': 'These dates are already blocked.'})

            PropertyBlockDate.objects.create(
                property=property_obj,
                start_date=start_date,
                end_date=end_date,
                reason='Blocked via Calendar'
            )
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
# from .models import PropertyBlock  # Import your Block/Booking model here

@login_required
@require_POST
def ajax_unblock_dates(request):
    try:
        data = json.loads(request.body)
        booking_id = data.get('booking_id')
        
        if not booking_id:
            return JsonResponse({'success': False, 'error': 'ID is required'})

        # Handle 'block-' prefix sent from frontend
        if str(booking_id).startswith('block-'):
            pk = str(booking_id).replace('block-', '')
            block = get_object_or_404(PropertyBlockDate, id=pk)
            
            # Ensure the user has permission to delete this block
            if block.property.created_by_id not in get_visible_user_ids(request.user):
                return JsonResponse({'success': False, 'error': 'Permission denied'})
                
            block.delete()
            return JsonResponse({'success': True})
            
        return JsonResponse({'success': False, 'error': 'Invalid block ID'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})









### New Section Added by subhankar ####



class ListingPageView(ListView):
    model = Property
    template_name = 'frontend/public_host_website/listing.html'
    context_object_name = 'properties'
    paginate_by = 6

    def get_queryset(self):
        short_code = self.kwargs.get('short_code')
        check_in = self.request.GET.get('check_in')
        check_out = self.request.GET.get('check_out')
        guests = self.request.GET.get('guests')
        
        if short_code:
            # Public access via host's alphanumeric short_code
            queryset = Property.objects.filter(created_by__short_code=short_code, status='Active')
        elif self.request.user.is_authenticated:
            # Authenticated user viewing their own listings
            queryset = Property.objects.filter(created_by__in=get_visible_user_ids(self.request.user), status='Active')
        else:
            return Property.objects.none()

        # Filter by availability if dates are provided
        if check_in and check_out:
            try:
                check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
                check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()

                if check_out_date > check_in_date:
                    nights = (check_out_date - check_in_date).days
                    queryset = queryset.filter(minimum_booking__lte=nights)

                    # Exclude overlapping bookings
                    overlapping_bookings = Booking.objects.filter(
                        check_in_date__lt=check_out_date,
                        check_out_date__gt=check_in_date,
                        status='confirmed'
                    )
                    queryset = queryset.exclude(id__in=overlapping_bookings.values_list('property_id', flat=True))

                    # Exclude overlapping blocks
                    overlapping_blocks = PropertyBlockDate.objects.filter(
                        is_active=True,
                        start_date__lt=check_out_date,
                        end_date__gt=check_in_date
                    )
                    queryset = queryset.exclude(id__in=overlapping_blocks.values_list('property_id', flat=True))
            except (ValueError, TypeError):
                pass

        if guests:
            try:
                queryset = queryset.filter(guest__gte=int(guests))
            except (ValueError, TypeError):
                pass
        
        return queryset.order_by('title')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        short_code = self.kwargs.get('short_code')
        
        if short_code:
            context['host'] = get_object_or_404(MyUser, short_code=short_code)
        elif self.request.user.is_authenticated:
            context['host'] = self.request.user
        else:
            raise Http404("Host or properties not found.")

        context['check_in'] = self.request.GET.get('check_in', '')
        context['check_out'] = self.request.GET.get('check_out', '')
        context['guests_count'] = self.request.GET.get('guests', '1')

        num_nights = 0
        check_in_str = self.request.GET.get('check_in', '')
        check_out_str = self.request.GET.get('check_out', '')
        if check_in_str and check_out_str:
            try:
                ci = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                co = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                if co > ci:
                    num_nights = (co - ci).days
            except (ValueError, TypeError):
                pass
        context['num_nights'] = num_nights

        return context




class ListingDetailView(DetailView):
    model = Property
    template_name = 'frontend/public_host_website/listing_details.html'
    context_object_name = 'property'

    def get_object(self, queryset=None):
        # Standard detail behavior when pk/slug is provided in URL.
        if self.kwargs.get('pk') or self.kwargs.get('slug'):
            return super().get_object(queryset)

        # Graceful fallback for /property/listing_details/ (no identifier provided).
        queryset = queryset or self.get_queryset()
        if self.request.user.is_authenticated:
            own_property = queryset.filter(created_by__in=get_visible_user_ids(self.request.user)).first()
            if own_property:
                return own_property

        fallback_property = queryset.first()
        if fallback_property:
            return fallback_property

        raise Http404("No property found for listing detail view.")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['host'] = self.object.created_by
        context['images'] = self.object.images.all()
        context['amenities'] = self.object.amenities.all().order_by('name')
        context['short_code']= self.kwargs.get('short_code')  if self.kwargs.get('short_code') else None
        return context


class RequestBokPageView(DetailView):
    model = Property
    template_name = 'frontend/public_host_website/request_book.html'
    context_object_name = 'property'

    def get_object(self, queryset=None):
        # Standard detail behavior when pk/slug is provided in URL.
        if self.kwargs.get('pk') or self.kwargs.get('slug'):
            return super().get_object(queryset)

        # Graceful fallback for /property/listing/ (no identifier provided).
        queryset = queryset or self.get_queryset()
        if self.request.user.is_authenticated:
            own_property = queryset.filter(created_by__in=get_visible_user_ids(self.request.user)).first()
            if own_property:
                return own_property

        fallback_property = queryset.first()
        if fallback_property:
            return fallback_property

        raise Http404("No property found for home page view.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['host'] = self.object.created_by
        return context

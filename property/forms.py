from django import forms
from .models import Property, PropertyImage, PropertyDocument, Amenities
from datetime import datetime, timedelta

# Generate all 30-min interval time choices
def generate_time_choices():
    times = []
    current = datetime.strptime("00:00", "%H:%M")
    end = datetime.strptime("23:30", "%H:%M")
    while current <= end:
        times.append((
            current.strftime("%H:%M"),   # value stored in DB
            current.strftime("%I:%M %p") # user-friendly display
        ))
        current += timedelta(minutes=30)
    return times

TIME_CHOICES = generate_time_choices()

class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        exclude = ['slug', 'created_at', 'created_by', 'updated_at', 'id', 'ical_token']  # Exclude auto-generated fields
        
        widgets = {
            # Basic Details
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter listing title'}),
            'description': forms.Textarea(attrs={'class': 'form-input form-textarea', 'placeholder': 'Describe your property...'}),
            
            # Address
            'street_address': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '123 Main Street'}),
            'city': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'New York'}),
            'zip': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': '10001',}),
            'country': forms.Select(attrs={'class': 'form-input country', 'id': 'country'}),
            'state': forms.Select(attrs={'class': 'form-input state', 'id': 'state'}),
            
            # Property Details
            'guest': forms.NumberInput(attrs={'class': 'form-input', 'min': '1', 'value': '1'}),
            'bathroom_type': forms.Select(attrs={'class': 'form-input'}),
            'property_type': forms.Select(attrs={'class': 'form-input'}),
            'bed_type': forms.Select(attrs={'class': 'form-input'}),
            'status': forms.Select(attrs={'class': 'form-input'}),
            
            # Passwords
            'room_password': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter room password', 'type': 'password'}),
            'network_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter WiFi network name'}),
            'wifi_password': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter WiFi password', 'type': 'password'}),
            
            # Booking Details
            'minimum_booking': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Enter nights', 'min': '1'}),
            'youtube_link': forms.URLInput(attrs={'class': 'form-input', 'placeholder': 'Enter YouTube link'}),
            
            # Check-in/Check-out - using hidden fields since template has custom dropdowns
            'check_in_time': forms.HiddenInput(attrs={'id': 'checkin_time_input'}),
            'check_out_time': forms.HiddenInput(attrs={'id': 'checkout_time_input'}),
            
            # Instructions and Rules
            'email_guest': forms.CheckboxInput(attrs={'id': 'emailGuest'}),
            'rules': forms.Textarea(attrs={'class': 'form-input form-textarea', 'placeholder': 'Enter your cancellation policy and house rules...'}),
            'house_rules': forms.Textarea(attrs={'class': 'form-input form-textarea', 'placeholder': 'Enter your house rules...'}),
            'cancellation_policy': forms.Textarea(attrs={'class': 'form-input form-textarea', 'placeholder': 'Enter your cancellation policy...'}),

            # Pricing
            'price_per_night': forms.NumberInput(attrs={'class': 'form-input', 'min': '0', 'step': '0.01'}),
            'application_fees': forms.NumberInput(attrs={'class': 'form-input', 'min': '0', 'step': '0.01'}),
            'cleaning_fee': forms.NumberInput(attrs={'class': 'form-input', 'min': '0', 'step': '0.01'}),
            'refundable_deposit': forms.NumberInput(attrs={'class': 'form-input', 'min': '0', 'step': '0.01'}),
            
            # Amenities - this will be handled separately in the template
            'amenities': forms.CheckboxSelectMultiple(attrs={'class': 'amenities-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        clone_from_id = kwargs.pop('clone_from_id', None)
        super().__init__(*args, **kwargs)

        # Initialize country and state choices
        self.fields['country'].choices = [('', 'Select Country')]
        self.fields['state'].choices = [('', 'Select State')]

        if self.instance and self.instance.pk: # For editing an existing property
            self.fields['country'].widget.attrs['data-selected'] = self.instance.country
            self.fields['state'].widget.attrs['data-selected'] = self.instance.state

            # Set initial values for time fields in 24-hour format (HH:MM)
            if self.instance.check_in_time:
                if hasattr(self.instance.check_in_time, 'strftime'):
                    self.fields['check_in_time'].initial = self.instance.check_in_time.strftime('%H:%M')
                else:
                    # Already a string, just use first 5 chars (HH:MM)
                    self.fields['check_in_time'].initial = str(self.instance.check_in_time)[:5]
            else:
                self.fields['check_in_time'].initial = '15:00'  # Default 3:00 PM
                
            if self.instance.check_out_time:
                if hasattr(self.instance.check_out_time, 'strftime'):
                    self.fields['check_out_time'].initial = self.instance.check_out_time.strftime('%H:%M')
                else:
                    self.fields['check_out_time'].initial = str(self.instance.check_out_time)[:5]
            else:
                self.fields['check_out_time'].initial = '10:00'  # Default 10:00 AM
        else:
            # Set defaults for new properties
            self.fields['check_in_time'].initial = '15:00'  # 3:00 PM
            self.fields['check_out_time'].initial = '10:00'  # 10:00 AM

        if clone_from_id: # For cloning a property
            try:
                original_property = Property.objects.get(pk=clone_from_id)
                self.fields['country'].widget.attrs['data-selected'] = original_property.country
                self.fields['state'].widget.attrs['data-selected'] = original_property.state
            except Property.DoesNotExist:
                pass
        
        # Make required fields more explicit
        required_fields = [
            'title', 'description', 'street_address', 'city', 'zip', 'country', 'state',
            'guest', 'bathroom_type', 'property_type', 'bed_type', 'status',
            'minimum_booking', 'check_in_time', 'check_out_time', 'price_per_night'
        ]
        
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True
        
        # Optional fields
        optional_fields = [
            'room_password', 'network_name',  'wifi_password', 'youtube_link', 'email_guest', 
            'rules', 'application_fees', 'cleaning_fee', 'refundable_deposit', 'amenities'
        ]
        
        for field_name in optional_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False

    def clean_price_per_night(self):
        price = self.cleaned_data.get('price_per_night')
        if price is not None and price <= 0:
            raise forms.ValidationError("Price per night must be greater than 0.")
        return price

    def clean_guest(self):
        guest = self.cleaned_data.get('guest')
        if guest is not None and guest < 1:
            raise forms.ValidationError("Number of guests must be at least 1.")
        return guest

    def clean_minimum_booking(self):
        booking = self.cleaned_data.get('minimum_booking')
        if booking is not None and booking < 1:
            raise forms.ValidationError("Minimum booking must be at least 1 night.")
        return booking

class PropertyImageForm(forms.ModelForm):
    class Meta:
        model = PropertyImage
        fields = ['image', 'is_primary']

class PropertyDocumentForm(forms.ModelForm):
    class Meta:
        model = PropertyDocument
        fields = ['document', 'name']
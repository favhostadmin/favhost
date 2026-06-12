from django import forms
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from .models import *
from property.models import Property
from accounts.utils import get_visible_user_ids


def generate_time_choices():
    times = []
    current = datetime.strptime("00:00", "%H:%M")
    end = datetime.strptime("23:30", "%H:%M")
    while current <= end:
        times.append((
            current.strftime("%H:%M"),
            current.strftime("%I:%M %p")
        ))
        current += timedelta(minutes=30)
    return times

TIME_CHOICES = generate_time_choices()


class PropertySelectWidget(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            try:
                property_obj = Property.objects.select_related().get(pk=value)
                option['attrs']['data-image'] = property_obj.get_primary_image_url()
                option['attrs']['data-location'] = property_obj.location_display()
                option['attrs']['data-price'] = property_obj.price_per_night
                option['attrs']['data-cleaning-fee'] = property_obj.cleaning_fee
                option['attrs']['data-refundable-deposit'] = property_obj.refundable_deposit
                option['attrs']['data-guest'] = property_obj.guest
            except Property.DoesNotExist:
                option['attrs']['data-image'] = '/static/img/property/placeholder-image.png'
        return option


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class BookingForm(forms.ModelForm):
    guest_images = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'accept': 'image/*', 'style': 'display: none;'
        }),
        required=False
    )
    guest_attachments = MultipleFileField(
        widget=MultipleFileInput(attrs={'style': 'display: none;'}),
        required=False)

    class Meta:
        model = Booking
        exclude = ['id', 'created_at']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input', 
                'placeholder': 'Enter first name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-input', 
                'placeholder': 'Enter last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input', 
                'placeholder': 'mail@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input', 
                'id': 'phone', 
                'placeholder': 'Enter phone number',
                'type': 'tel'
            }),
            'guest_count': forms.TextInput(attrs={
                'class': 'form-input', 
                'placeholder': 'Number of guests',
                'type': 'number',
                'min': '1'
            }),
            'channel': forms.Select(attrs={
                'class': 'form-input'
            }),
            'check_in_date': forms.DateInput(attrs={
                'class': 'form-input', 
                'type': 'date'
            }),
            'check_out_date': forms.DateInput(attrs={
                'class': 'form-input', 
                'type': 'date'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input', 
                'rows': 4, 
                'placeholder': 'Enter any special requests or notes...'
            }),
            'property': PropertySelectWidget(attrs={
                'class': 'form-control property-select'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input', 
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['channel'].queryset = BookingChannel.objects.all()
        self.fields['channel'].empty_label = "Select a channel"

        if user:
            queryset = Property.objects.filter(created_by__in=get_visible_user_ids(user), status='Active')
            self.fields['property'].queryset = queryset
            self.fields['property'].widget.choices = [(p.id, p.title) for p in queryset]
        else:
            self.fields['property'].queryset = Property.objects.none()

        self.fields['check_in_time'] = forms.ChoiceField(
            choices=TIME_CHOICES, 
            widget=forms.Select(attrs={'class': 'form-input'})
        )
        self.fields['check_out_time'] = forms.ChoiceField(
            choices=TIME_CHOICES, 
            widget=forms.Select(attrs={'class': 'form-input'})
        )

        if self.instance and self.instance.pk:
            if self.instance.check_in_time:
                if hasattr(self.instance.check_in_time, 'strftime'):
                    self.fields['check_in_time'].initial = self.instance.check_in_time.strftime('%H:%M')
                else:
                    self.fields['check_in_time'].initial = str(self.instance.check_in_time)[:5]
            else:
                self.fields['check_in_time'].initial = '15:00'
                
            if self.instance.check_out_time:
                if hasattr(self.instance.check_out_time, 'strftime'):
                    self.fields['check_out_time'].initial = self.instance.check_out_time.strftime('%H:%M')
                else:
                    self.fields['check_out_time'].initial = str(self.instance.check_out_time)[:5]
            else:
                self.fields['check_out_time'].initial = '10:00'
        else:
            self.fields['check_in_time'].initial = '15:00'
            self.fields['check_out_time'].initial = '10:00'

        required_fields = [
            'first_name', 'last_name', 'email', 'phone', 'guest_count',
            'channel', 'check_in_time', 'check_out_time',
            'check_in_date', 'check_out_date', 'property'
        ]
        
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True
        
        optional_fields = ['notes', 'guest_images', 'guest_attachments']
        for field_name in optional_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False
        
        self.fields['guest_count'].choices = [('', 'Select a property first')]
        self.fields['guest_count'].widget.attrs.update({'class': 'form-control'})


class GuestImageForm(forms.ModelForm):
    class Meta:
        model = GuestImage
        fields = ['image']


class GuestDocumentForm(forms.ModelForm):
    class Meta:
        model = GuestDocument
        fields = ['document', 'name']
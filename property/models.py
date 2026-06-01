from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
import uuid
import os
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.contrib.staticfiles.storage import staticfiles_storage

from booking.models import BookingChannel
from .enums import *

def validate_amenity_icon(value):
    """Validator to ensure uploaded file is an SVG, PNG, or JPG."""
    ext = os.path.splitext(value.name)[1]
    valid_extensions = ['.svg', '.png', '.jpg', '.jpeg']
    if ext.lower() not in valid_extensions:
        raise ValidationError('Unsupported file extension. Only SVG, PNG, and JPG files are allowed.')


class Amenities(models.Model):
    icon = models.FileField(upload_to='amenities/icons/', null=False, blank=False, validators=[validate_amenity_icon])
    name = models.CharField(max_length=100, null=False, blank=False)
    class Meta:
        ordering=['name']

    def __str__(self):
        return f"{self.name}"

class Property(models.Model):
    # UUID Primary Key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Basic Details
    title = models.CharField(max_length=200)
    description = models.TextField()
    
    # Address
    country = models.CharField(max_length=100)
    street_address = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    zip = models.CharField(max_length=20)
    state = models.CharField(max_length=100)
    
    # Property Details
    guest = models.PositiveIntegerField(default=1, verbose_name='Number of Guests (max)')
    bathroom_type = models.CharField(max_length=20, choices=BATHROOM_TYPES)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES)
    bed_type = models.CharField(max_length=20, choices=BED_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    
    # Passwords
    room_password = models.CharField(max_length=100, blank=True, null=True)
    network_name = models.CharField(max_length=100, blank=True, null=True)
    wifi_password = models.CharField(max_length=100, blank=True, null=True)
    
    # Booking Details
    minimum_booking = models.PositiveIntegerField(default=1, verbose_name='Minimum Booking (nights)')
    youtube_link = models.URLField(blank=True, null=True)
    
    # Check-in/Check-out
   
    check_in_time = models.TimeField(default="15:00")   # 3:00 PM
    check_out_time = models.TimeField(default="10:00")  # 10:00 AM
    
    # Instructions and Rules
    email_guest = models.BooleanField(default=False, verbose_name='Email guest before Check-in')
    rules = models.TextField(blank=True, null=True, verbose_name='Cancellation, Other Policies and Rules')
    
    # Pricing
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Price/Night')
    application_fees = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    cleaning_fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    refundable_deposit = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    
    # Relationships
    amenities = models.ManyToManyField(Amenities, blank=True, related_name='properties')
    
    # Meta
    slug = models.SlugField(max_length=255, unique=False, editable=True, null=True, blank=True)
    ical_token = models.UUIDField(default=uuid.uuid4, unique=False, editable=True, help_text="Unique token for iCal feed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("accounts.MyUser", on_delete=models.SET_NULL, null=True, related_name='properties_created')


    def location_display(self):
        # Adjust as needed for your preferred format
        return f"{self.city}, {self.state}"

    def get_primary_image_url(self):
        """Returns the URL for the primary image, or the first image, or a placeholder."""
        primary_image = self.images.filter(is_primary=True).first()
        if primary_image and hasattr(primary_image.image, 'url'):
            return primary_image.image.url
        
        first_image = self.images.first()
        if first_image and hasattr(first_image.image, 'url'):
            return first_image.image.url
        return staticfiles_storage.url('img/property/placeholder-image.png')

    def get_absolute_url(self):
        """Returns the public-facing URL for this property listing."""
        # Redirects to the public DetailView using the host's short_code and property slug
        if self.created_by and getattr(self.created_by, 'short_code', None):
            return reverse('property:listing-detail-slug', kwargs={
                'short_code': self.created_by.short_code,
                'slug': self.slug
            })
        # Fallback to internal detail view if host info is missing
        return reverse('property:property-detail', kwargs={'slug': self.slug})

    def get_public_listing_url(self):
        """Returns the URL for the host's public collection of properties."""
        if self.created_by and getattr(self.created_by, 'short_code', None):
            return reverse('property:listing-page-public', kwargs={
                'short_code': self.created_by.short_code
            })
        return reverse('property:listing-page')

    @property
    def get_ical_url(self):
        """Returns the relative URL for the iCal feed."""
        url = reverse('property:ical-export', kwargs={'pk': self.id})
        return f"{url}?t={self.ical_token}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Property.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name = "Property"
        verbose_name_plural = "Properties"
        ordering = ['title','created_at']

class PropertyImage(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='property_images/')
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.property.title} - Image"
    
    class Meta:
        ordering = ['-is_primary', 'created_at']

class PropertyDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('check_in', 'Check-in Instruction'),
        ('check_out', 'Check-out Instruction'),
    ]

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='property_documents/')
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES, default='check_in')
    
    def __str__(self):
        return f"{self.property.title} - {self.name}"
    
class PropertyBlockDate(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='blocked_dates')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    external_uid = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Blocked: {self.property.title} ({self.start_date} to {self.end_date})"

class PropertyChannel(models.Model):
    """
    Represents a specific channel integration for a property.
    """
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='property_channels')
    channel_type = models.ForeignKey(BookingChannel, on_delete=models.CASCADE)
    calendar_link = models.URLField(max_length=1000)
    is_connected = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.property.title} - {self.channel_type.name}"
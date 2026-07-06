from django.db import models, transaction
import uuid
import builtins
from .enums import *


class BookingChannel(models.Model):
    name = models.CharField(max_length=100, unique=True)
    icon = models.ImageField(upload_to='booking_channels/', null=True, blank=True, verbose_name="Black icon")
    white_icon = models.ImageField(upload_to='booking_channels/', null=True, blank=True, verbose_name="White icon")
    color = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        return self.name


class Booking(models.Model):
    STATUS_CHOICES = (
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_id = models.PositiveIntegerField(null=True, blank=True)
    first_name = models.CharField(max_length=100,null=True, blank=True)
    last_name = models.CharField(max_length=100,null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    country_code = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=20,null=True, blank=True)
    street_address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    zip = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    nationality = models.CharField(max_length=100, null=True, blank=True)
    vehicle_information = models.CharField(max_length=255, null=True, blank=True)
    guest_count = models.PositiveIntegerField()
    # booking_channel = models.CharField(max_length=100, choices=BOOKING_CHANNELS, default='personal_website')
    channel = models.ForeignKey(BookingChannel, on_delete=models.SET_NULL, null=True, blank=True)
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    check_in_date = models.DateField(null=True, blank=True)
    check_out_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    purpose_of_stay = models.CharField(max_length=255, null=True, blank=True)

    property = models.ForeignKey('property.Property', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Price per night', default=0.00)
    cleaning_fee = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Cleaning fee', default=0.00)
    application_fee = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Application fee', default=0.00)
    deposit_fee = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Deposit fee', default=0.00)
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='TotalPrice', default=0.00)


    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    # cancelled_at = models.DateTimeField(null=True, blank=True)

    external_uid = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True
    )

    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True)

    checkin_email_sent = models.BooleanField(default=False)
    checkout_email_sent = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Booking"
        verbose_name_plural = "Bookings"
        ordering = ['-created_at']

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self.booking_id:
            # Lock the table to prevent race conditions
            last_booking = Booking.objects.select_for_update().order_by('booking_id').last()
            if last_booking and last_booking.booking_id is not None:
                self.booking_id = last_booking.booking_id + 1
            else:
                self.booking_id = 1000
        super().save(*args, **kwargs)

    @builtins.property
    def total_nights(self):
        if self.check_in_date and self.check_out_date:
            nights = (self.check_out_date - self.check_in_date).days
            return max(nights, 0)
        return 0
        
class GuestImage(models.Model):
    reservation = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='guest_images/')
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class GuestDocument(models.Model):
    reservation = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='guest_documents/')
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    
class Payment(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    type = models.CharField(null=True, blank=True, max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    expected_payment_date = models.DateTimeField(null=True, blank=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Payment of {self.amount} for Booking {self.booking.id}"


class PaymentAttachment(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='payment_attachments/')
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} for Payment {self.payment.id}"



class Expense(models.Model):
    """A host-recorded business expense, used by the Accounting page.

    Like every other monetary value on the platform, ``amount`` is stored in the
    canonical USD base (see accounts/currency.py); views convert the host-entered
    display-currency figure to USD on save and the templates render it back with
    the {% money %} tag. ``property`` is optional so an expense can be tied to a
    specific listing or kept as a business-wide cost.
    """
    CATEGORY_CHOICES = (
        ('Mortgage', 'Mortgage'),
        ('Salaries', 'Salaries'),
        ('Supplies', 'Supplies'),
        ('Utilities', 'Utilities'),
        ('Repairs and maintenance', 'Repairs and maintenance'),
        ('Marketing', 'Marketing'),
        ('Tax', 'Tax'),
        ('Insurance', 'Insurance'),
        ('Legal expenses', 'Legal expenses'),
        ('Cleaning fees', 'Cleaning fees'),
        ('Other expenses', 'Other expenses'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey('accounts.MyUser', on_delete=models.CASCADE, related_name='expenses')
    property = models.ForeignKey('property.Property', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='Other expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Amount (USD)')
    date = models.DateField()
    note = models.TextField(null=True, blank=True)
    attachment = models.FileField(upload_to='expense_attachments/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.category} - {self.amount} ({self.date})"


class Enquiry(models.Model):
    unique_id = models.UUIDField(default=uuid.uuid4,unique=True, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    country_code = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    phone_code = models.CharField(max_length=10, null=True, blank=True)

    notes_for_host = models.TextField(blank=True, null=True)
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)

    pets = models.PositiveBigIntegerField(default=0)
    pet_details = models.TextField(blank=True, null=True)

    check_in_date = models.DateField()
    check_out_date = models.DateField()

    property = models.ForeignKey('property.Property', on_delete=models.CASCADE, related_name='enquiries')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archive = models.BooleanField(default=False)
    is_booked = models.BooleanField(default=False)

    reservation = models.OneToOneField(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='enquiry')

    def save(self, *args, **kwargs):
        if not self.unique_id:
            self.unique_id = uuid.uuid4()
        super().save(*args, **kwargs)

    @builtins.property
    def total_nights(self):
        if self.check_in_date and self.check_out_date:
            nights = (self.check_out_date - self.check_in_date).days
            return max(nights, 0)
        return 0

    @builtins.property
    def is_available(self):
        if not self.property or not self.check_in_date or not self.check_out_date:
            return False
        if self.check_out_date <= self.check_in_date:
            return False

        from property.models import PropertyBlockDate

        has_conflict = Booking.objects.filter(
            property=self.property,
            status='confirmed',
            check_in_date__lt=self.check_out_date,
            check_out_date__gt=self.check_in_date,
        ).exists()

        has_blocked_date = PropertyBlockDate.objects.filter(
            property=self.property,
            start_date__lt=self.check_out_date,
            end_date__gt=self.check_in_date,
        ).exists()

        return not has_conflict and not has_blocked_date

    @builtins.property
    def total_guests(self):
        # return self.adults + self.children + self.pets
        return self.adults
    
    @builtins.property
    def guest_name(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        verbose_name = "Enquiry"
        verbose_name_plural = "Enquiries"
        ordering = ['-created_at']

class EnquiryImage(models.Model):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='enquiry_images/')
    created_at = models.DateTimeField(auto_now_add=True)

class EnquiryDocument(models.Model):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='enquiry_documents/')
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

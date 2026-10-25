import uuid

from django.db import models


class ImageJob(models.Model):
    """One image going through the enhance pipeline.

    The *_key fields are storage keys (never URLs): the original and clean files
    live in private storage and are only ever served through session-checked
    views, so nothing here is publicly reachable by guessing a path.
    """
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    # Uploaded/scraped but not enhanced yet: only the first photo of a batch is enhanced as a preview;
    # the rest wait here until the visitor presses Continue (so no AI cost is spent before they opt in).
    STATUS_HELD = 'held'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_HELD, 'Waiting for visitor'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The listing page the image came from (blank for direct uploads).
    source_url = models.URLField(max_length=2000, blank=True)
    # The scraped image itself; the worker downloads it. Blank for uploads,
    # whose bytes are already stored when the job is created.
    image_url = models.URLField(max_length=2000, blank=True)
    original_key = models.CharField(max_length=500, blank=True)
    watermarked_key = models.CharField(max_length=500, blank=True)
    clean_key = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error = models.TextField(blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_cents = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    session_key = models.CharField(max_length=64, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id} ({self.status})'


class BoosterLead(models.Model):
    FEATURE_IMAGE = 'image'
    FEATURE_REPORT = 'report'
    FEATURE_CHOICES = [
        (FEATURE_IMAGE, 'Photo Enhancer'),
        (FEATURE_REPORT, 'Listing Audit'),
    ]

    name = models.CharField(max_length=120)
    email = models.EmailField()
    feature = models.CharField(max_length=10, choices=FEATURE_CHOICES)
    source_url = models.URLField(max_length=2000, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} <{self.email}>'


class ListingReport(models.Model):
    """One Listing Audit run: the data we gathered about a listing and the AI's analysis of it."""
    PLATFORM_AIRBNB = 'airbnb'
    PLATFORM_BOOKING = 'booking'
    PLATFORM_FAVHOST = 'favhost'
    PLATFORM_OTHER = 'other'
    PLATFORM_CHOICES = [
        (PLATFORM_AIRBNB, 'Airbnb'),
        (PLATFORM_BOOKING, 'Booking.com'),
        (PLATFORM_FAVHOST, 'FavHost'),
        (PLATFORM_OTHER, 'Other'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Blank when the listing details were pasted in by hand.
    source_url = models.URLField(max_length=2000, blank=True)
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES, default=PLATFORM_OTHER, db_index=True)
    # Exactly what was sent to the model (absent fields are null, never guessed).
    scraped_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error = models.TextField(blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_cents = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    session_key = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id} ({self.platform}, {self.status})'

"""First-party traffic log powering the owner console's audience report.

Deliberately tiny, and deliberately not Google Analytics:

* One row per **public** page view. Requests from signed-in users are never
  logged — a host working inside their own dashboard is not "site traffic".
* No cookie is set and no personal data is stored. The visitor key is a
  salted hash of IP + user agent + *today's date*, so unique-visitors-per-day
  is exact while nothing identifies a person or survives into tomorrow.
* Nothing here is ever shown to hosts; it exists only for the platform owner.
"""
from django.db import models


class SeoContentBlock(models.Model):
    """One overridable piece of content on the public /home landing page.

    ``key`` matches an entry in ``controlpanel.seo_fields.SEO_FIELDS`` — that
    registry is the source of truth for which keys exist; a row here only
    exists once someone has actually overridden the built-in default, so an
    untouched field never needs a migration-time data seed.
    """
    TEXT = 'text'
    TEXTAREA = 'textarea'
    IMAGE = 'image'

    FIELD_TYPES = [
        (TEXT, 'Text'),
        (TEXTAREA, 'Textarea'),
        (IMAGE, 'Image'),
    ]

    key = models.CharField(max_length=100, unique=True)
    section = models.CharField(max_length=50, db_index=True)
    label = models.CharField(max_length=150)
    field_type = models.CharField(max_length=10, choices=FIELD_TYPES, default=TEXT)
    text_value = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='seo/', blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['section', 'key']
        verbose_name = 'SEO content block'

    def __str__(self):
        return self.key


class PageView(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=300)
    # daily-rotating hash — see controlpanel.middleware.visitor_key()
    visitor_key = models.CharField(max_length=32, db_index=True)
    # netloc only ("google.com"), never the full referring URL
    referrer_host = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        verbose_name = 'page view'
        indexes = [
            models.Index(fields=['created_at', 'visitor_key']),
            models.Index(fields=['created_at', 'path']),
        ]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d} {self.path}'

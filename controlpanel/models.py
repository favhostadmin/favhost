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

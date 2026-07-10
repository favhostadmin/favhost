from django.db import models
from property.models import Property


class Cleaner(models.Model):
    """A named housekeeping staff member a host can assign to listings.

    Shared across a host's account the same way properties are (see
    accounts.utils.get_visible_user_ids / get_effective_user) — created_by
    is the owning host, so co-hosts see and manage the same roster.
    """
    created_by = models.ForeignKey("accounts.MyUser", on_delete=models.SET_NULL, null=True, related_name='cleaners')
    name       = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    # "Deleting" a cleaner from the roster soft-deletes it (is_active=False)
    # rather than removing the row — HousekeepingStatus.cleaner FKs to it
    # from any date (past, today, future) stay intact so already-made
    # assignments keep showing the name. Only the *selectable* roster
    # (see frontdesk/views.py::_cleaner_roster) excludes inactive cleaners.
    is_active  = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = ('created_by', 'name')

    def __str__(self):
        return self.name


class HousekeepingStatus(models.Model):
    STATUS_CHOICES = [
        ('Dirty',             'Dirty'),
        ('In-Progress',       'In-Progress'),
        ('Clean-Uninspected', 'Clean-Uninspected'),
        ('Clean-Inspected',   'Clean-Inspected'),
        ('Clean-Ready',       'Clean-Ready'),
        ('Out-of-Service',    'Out-of-Service'),
    ]

    property   = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='hk_statuses')
    date       = models.DateField()
    # No default here on purpose — the dropdown should show its "Select
    # Status" placeholder until a host explicitly picks one, rather than
    # silently pre-selecting a guess (see frontdesk/views.py::_fd_data).
    status     = models.CharField(max_length=32, choices=STATUS_CHOICES, null=True, blank=True, default=None)
    cleaner    = models.ForeignKey(Cleaner, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('property', 'date')

    def __str__(self):
        return f"{self.property.title} — {self.date} — {self.status}"

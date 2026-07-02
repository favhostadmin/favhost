from django.db import models
from property.models import Property


class HousekeepingStatus(models.Model):
    STATUS_CHOICES = [
        ('Dirty',             'Dirty'),
        ('In-Progress',       'In-Progress'),
        ('Clean-Uninspected', 'Clean-Uninspected'),
        ('Clean-Inspected',   'Clean-Inspected'),
        ('Clean-Ready',       'Clean-Ready'),
        ('Out-of-Service',    'Out-of-Service'),
    ]

    property   = models.OneToOneField(Property, on_delete=models.CASCADE, related_name='hk_status')
    status     = models.CharField(max_length=32, choices=STATUS_CHOICES, default='Clean-Inspected')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.property.title} — {self.status}"

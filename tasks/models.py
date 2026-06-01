from django.db import models
from accounts.models import MyUser


class Task(models.Model):
    REPEAT_CHOICES = [('None', 'None'), ('Daily', 'Daily'), ('Weekly', 'Weekly'), ('Monthly', 'Monthly'), ('Quarterly', 'Quarterly'), ('Yearly', 'Yearly')]
    TASK_TYPE_CHOICES = [('cleaning', 'Cleaning'), ('maintenance', 'Maintenance'), ('payment', 'Payment'), ('other', 'Other')]

    property = models.ForeignKey('property.Property', on_delete=models.CASCADE)
    details = models.TextField(blank=True, null=True)
    date = models.DateField(blank=True, null=True)
    time = models.TimeField(blank=True, null=True)
    repeat = models.CharField(max_length=50, choices=REPEAT_CHOICES,blank=True, null=True)
    repeat_till = models.DateField(blank=True, null=True)
    task_type = models.CharField(max_length=100, choices=TASK_TYPE_CHOICES,blank=True, null=True)
    other_explanation = models.TextField(blank=True, null=True)
    assigned_to = models.CharField(max_length=100,blank=True, null=True)
    phone = models.CharField(max_length=20,null=True, blank=True)
    country_code = models.CharField(max_length=10, null=True, blank=True)

    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    created_by = models.ForeignKey(MyUser, on_delete=models.CASCADE)
    recurrence_id = models.CharField(max_length=256, null=True, blank=True)

    def __str__(self):
        return f"Task for {self.property.title} on {self.date}"

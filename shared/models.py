from django.db import models


class CountryAndState(models.Model):
    country_name = models.CharField(max_length=150, db_index=True)
    country_code = models.CharField(max_length=10, blank=True, null=True)
    country_short = models.CharField(max_length=10, blank=True, null=True)
    state_name = models.CharField(max_length=150, blank=True, null=True)
    state_code = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        ordering = ['country_name', 'state_name']

    def __str__(self):
        return f"{self.country_name} - {self.state_name}" if self.state_name else self.country_name

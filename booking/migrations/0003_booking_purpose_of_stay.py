# Generated manually to add purpose_of_stay to Booking.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='purpose_of_stay',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]

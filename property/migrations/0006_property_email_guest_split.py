from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0005_property_rental_contract_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='email_guest_checkin',
            field=models.BooleanField(default=True, verbose_name='Email guest Check-in instructions'),
        ),
        migrations.AddField(
            model_name='property',
            name='email_guest_checkout',
            field=models.BooleanField(default=True, verbose_name='Email guest Check-out instructions'),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_myuser_trial_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='myuser',
            name='email_guest_checkin',
            field=models.BooleanField(default=True, help_text='Email guests their check-in instructions automatically.'),
        ),
        migrations.AddField(
            model_name='myuser',
            name='email_guest_checkout',
            field=models.BooleanField(default=True, help_text='Email guests their check-out instructions automatically.'),
        ),
    ]

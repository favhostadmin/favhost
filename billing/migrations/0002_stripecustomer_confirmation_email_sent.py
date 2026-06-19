from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='stripecustomer',
            name='confirmation_email_sent',
            field=models.BooleanField(default=False),
        ),
    ]

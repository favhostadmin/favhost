from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='myuser',
            name='trial_ending_email_sent',
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='myuser',
            name='trial_days',
            field=models.PositiveIntegerField(
                default=90,
                help_text="This account's free-trial length in days (set at signup).",
            ),
        ),
    ]

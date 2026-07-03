from django.db import migrations, models


def create_default_settings(apps, schema_editor):
    """Seed the single PlatformSetting row with sensible defaults."""
    PlatformSetting = apps.get_model('billing', 'PlatformSetting')
    PlatformSetting.objects.get_or_create(
        pk=1,
        defaults={
            'subscription_price': 9.99,
            'subscription_currency': 'USD',
            'subscription_interval': 'month',
            'free_trial_days': 90,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_create_missing_confirmation_email_sent'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subscription_price', models.DecimalField(decimal_places=2, default=9.99, max_digits=8)),
                ('subscription_currency', models.CharField(default='USD', max_length=10)),
                ('subscription_interval', models.CharField(default='month', max_length=20)),
                ('free_trial_days', models.PositiveIntegerField(default=90)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Platform Setting',
                'verbose_name_plural': 'Platform Settings',
            },
        ),
        migrations.RunPython(create_default_settings, migrations.RunPython.noop),
    ]

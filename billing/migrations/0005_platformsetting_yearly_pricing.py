from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_alter_platformsetting_free_trial_days_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsetting',
            name='subscription_price_yearly',
            field=models.DecimalField(
                decimal_places=2, default=99.99, max_digits=8,
                help_text='Yearly price shown across the platform (display only — '
                          'update Stripe separately for real billing).',
            ),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='subscription_interval_yearly',
            field=models.CharField(
                default='year', max_length=20,
                help_text='Yearly billing interval label, e.g. year.',
            ),
        ),
    ]

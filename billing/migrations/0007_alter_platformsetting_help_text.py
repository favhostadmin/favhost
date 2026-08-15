from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_platformsetting_stripe_price_ids'),
    ]

    operations = [
        migrations.AlterField(
            model_name='platformsetting',
            name='subscription_currency',
            field=models.CharField(
                default='USD', max_length=10,
                help_text='3-letter currency code, e.g. USD, EUR, GBP. Auto-filled from Stripe.',
            ),
        ),
        migrations.AlterField(
            model_name='platformsetting',
            name='subscription_interval',
            field=models.CharField(
                default='month', max_length=20,
                help_text='Billing interval label, e.g. month or year. Auto-filled from Stripe.',
            ),
        ),
        migrations.AlterField(
            model_name='platformsetting',
            name='subscription_interval_yearly',
            field=models.CharField(
                default='year', max_length=20,
                help_text='Yearly billing interval label, e.g. year. Auto-filled from Stripe.',
            ),
        ),
        migrations.AlterField(
            model_name='platformsetting',
            name='subscription_price',
            field=models.DecimalField(
                decimal_places=2, default=9.99, max_digits=8,
                help_text='Monthly price shown across the platform. Auto-filled from '
                          'the Stripe price ID above — do not edit directly.',
            ),
        ),
        migrations.AlterField(
            model_name='platformsetting',
            name='subscription_price_yearly',
            field=models.DecimalField(
                decimal_places=2, default=99.99, max_digits=8,
                help_text='Yearly price shown across the platform. Auto-filled from '
                          'the Stripe price ID above — do not edit directly.',
            ),
        ),
    ]

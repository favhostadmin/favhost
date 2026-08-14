from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_platformsetting_yearly_pricing'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsetting',
            name='stripe_price_id_monthly',
            field=models.CharField(
                blank=True, default='', max_length=255,
                help_text='Stripe Price ID for the monthly plan (e.g. price_1AbC...). '
                          'This is what Stripe actually charges. Create it in the '
                          'Stripe dashboard first, then paste it here — the amount, '
                          'currency and interval below are fetched from Stripe '
                          'automatically.',
            ),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='stripe_price_id_yearly',
            field=models.CharField(
                blank=True, default='', max_length=255,
                help_text='Stripe Price ID for the yearly plan. Same rules as the '
                          'monthly price ID above.',
            ),
        ),
    ]

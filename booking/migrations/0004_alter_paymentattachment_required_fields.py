import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Makes PaymentAttachment.created_at / file / name non-nullable to match the
    current model (these were null=True in 0001_initial). One-off defaults are
    supplied with preserve_default=False so any existing NULL rows are backfilled
    and the ALTER ... SET NOT NULL cannot fail on databases that already hold data.
    """

    dependencies = [
        ('booking', '0003_create_missing_paymentattachment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymentattachment',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='paymentattachment',
            name='file',
            field=models.FileField(default='', upload_to='payment_attachments/'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='paymentattachment',
            name='name',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
    ]

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0002_imagejob_ip_address'),
    ]

    operations = [
        migrations.CreateModel(
            name='ListingReport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_url', models.URLField(blank=True, max_length=2000)),
                ('platform', models.CharField(choices=[('airbnb', 'Airbnb'), ('booking', 'Booking.com'), ('favhost', 'FavHost'), ('other', 'Other')], db_index=True, default='other', max_length=10)),
                ('scraped_json', models.JSONField(blank=True, default=dict)),
                ('result_json', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('done', 'Done'), ('failed', 'Failed')], db_index=True, default='pending', max_length=12)),
                ('error', models.TextField(blank=True)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('cost_cents', models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ('session_key', models.CharField(db_index=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

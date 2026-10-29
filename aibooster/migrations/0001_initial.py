import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='BoosterLead',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('email', models.EmailField(max_length=254)),
                ('feature', models.CharField(choices=[('image', 'Image Booster'), ('report', 'Boost Report')], max_length=10)),
                ('source_url', models.URLField(blank=True, max_length=2000)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ImageJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_url', models.URLField(blank=True, max_length=2000)),
                ('image_url', models.URLField(blank=True, max_length=2000)),
                ('original_key', models.CharField(blank=True, max_length=500)),
                ('watermarked_key', models.CharField(blank=True, max_length=500)),
                ('clean_key', models.CharField(blank=True, max_length=500)),
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

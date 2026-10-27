import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0005_boosterlead_feature_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='imagejob',
            name='is_paid',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='listingreport',
            name='is_paid',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('photos', 'Photo Enhancer'), ('report', 'Listing Audit')], max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Awaiting payment'), ('paid', 'Paid')], db_index=True, default='pending', max_length=10)),
                ('session_key', models.CharField(db_index=True, max_length=64)),
                ('user_id', models.IntegerField(blank=True, null=True)),
                ('job_ids', models.JSONField(blank=True, default=list)),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('unit_amount', models.PositiveIntegerField(default=0)),
                ('amount_total', models.PositiveIntegerField(default=0)),
                ('currency', models.CharField(default='usd', max_length=3)),
                ('stripe_session_id', models.CharField(blank=True, db_index=True, max_length=255)),
                ('customer_email', models.EmailField(blank=True, max_length=254)),
                ('customer_name', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('report', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='orders', to='aibooster.listingreport')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]

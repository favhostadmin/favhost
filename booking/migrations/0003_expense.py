# Hand-written migration (NOT generated via makemigrations) for the Accounting
# page's Expense model. Team rule: run `migrate` only, never `makemigrations`.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('property', '0001_initial'),
        ('booking', '0002_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category', models.CharField(choices=[('Mortgage', 'Mortgage'), ('Salaries', 'Salaries'), ('Supplies', 'Supplies'), ('Utilities', 'Utilities'), ('Repairs and maintenance', 'Repairs and maintenance'), ('Marketing', 'Marketing'), ('Tax', 'Tax'), ('Insurance', 'Insurance'), ('Legal expenses', 'Legal expenses'), ('Cleaning fees', 'Cleaning fees'), ('Other expenses', 'Other expenses')], default='Other expenses', max_length=100)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Amount (USD)')),
                ('date', models.DateField()),
                ('note', models.TextField(blank=True, null=True)),
                ('attachment', models.FileField(blank=True, null=True, upload_to='expense_attachments/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expenses', to=settings.AUTH_USER_MODEL)),
                ('property', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expenses', to='property.property')),
            ],
            options={
                'verbose_name': 'Expense',
                'verbose_name_plural': 'Expenses',
                'ordering': ['-date', '-created_at'],
            },
        ),
    ]

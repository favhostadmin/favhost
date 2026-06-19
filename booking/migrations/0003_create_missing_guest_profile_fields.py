from django.db import migrations, models


def add_missing_booking_fields(apps, schema_editor):
    """
    Heal databases where booking_booking exists but some guest profile columns
    were never added.

    This is a no-op for databases that already have the fields.
    """
    table_name = 'booking_booking'
    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }

    Booking = apps.get_model('booking', 'Booking')
    fields = [
        ('street_address', models.CharField(max_length=255, null=True, blank=True)),
        ('city', models.CharField(max_length=100, null=True, blank=True)),
        ('zip', models.CharField(max_length=20, null=True, blank=True)),
        ('country', models.CharField(max_length=100, null=True, blank=True)),
        ('state', models.CharField(max_length=100, null=True, blank=True)),
        ('nationality', models.CharField(max_length=100, null=True, blank=True)),
        ('vehicle_information', models.CharField(max_length=255, null=True, blank=True)),
    ]

    for field_name, field in fields:
        if field_name in existing_columns:
            continue
        field.set_attributes_from_name(field_name)
        schema_editor.add_field(Booking, field)


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(add_missing_booking_fields, migrations.RunPython.noop),
    ]


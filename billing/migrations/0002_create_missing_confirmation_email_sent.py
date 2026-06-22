from django.db import migrations, models


def add_confirmation_email_sent_if_missing(apps, schema_editor):
    """
    Heal databases where billing_stripecustomer exists but the
    confirmation_email_sent column was never added.

    This is a no-op on healthy databases where the column already exists.
    """
    table_name = 'billing_stripecustomer'
    column_name = 'confirmation_email_sent'

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }

    if column_name in existing_columns:
        return

    StripeCustomer = apps.get_model('billing', 'StripeCustomer')
    field = models.BooleanField(default=False)
    field.set_attributes_from_name(column_name)
    schema_editor.add_field(StripeCustomer, field)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_confirmation_email_sent_if_missing, migrations.RunPython.noop),
    ]


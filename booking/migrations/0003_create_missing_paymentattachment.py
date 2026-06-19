from django.db import migrations


def create_paymentattachment_if_missing(apps, schema_editor):
    """
    Heal databases where 0001_initial is recorded as applied but the
    booking_paymentattachment table was never actually created (0001 was edited
    to add PaymentAttachment after it had already been applied on some databases).

    On a healthy DB (table already present, e.g. a fresh deploy) this is a no-op.
    """
    table = 'booking_paymentattachment'
    if table in schema_editor.connection.introspection.table_names():
        return
    PaymentAttachment = apps.get_model('booking', 'PaymentAttachment')
    schema_editor.create_model(PaymentAttachment)


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0002_initial'),
    ]

    operations = [
        # Reverse is a no-op: we never drop the table on rollback.
        migrations.RunPython(create_paymentattachment_if_missing, migrations.RunPython.noop),
    ]

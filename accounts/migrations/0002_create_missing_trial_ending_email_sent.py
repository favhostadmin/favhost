from django.db import migrations, models


def add_trial_ending_email_sent_if_missing(apps, schema_editor):
    """
    Heal databases where the accounts_myuser table exists but the
    trial_ending_email_sent column was never added.

    This is a no-op on healthy databases where the column already exists.
    """
    table_name = 'accounts_myuser'
    column_name = 'trial_ending_email_sent'

    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table_name
        )
    }

    if column_name in existing_columns:
        return

    MyUser = apps.get_model('accounts', 'MyUser')
    field = models.BooleanField(default=False)
    field.set_attributes_from_name(column_name)
    schema_editor.add_field(MyUser, field)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_trial_ending_email_sent_if_missing, migrations.RunPython.noop),
    ]


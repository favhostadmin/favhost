from django.db import migrations, models


class Migration(migrations.Migration):
    """Per-co-admin console section grants.

    Existing rows default to ``[]`` — no access to any data section until the
    owner grants one. Defaulting to "nothing" rather than "everything" means a
    forgotten row can never quietly hold more power than intended.
    """

    dependencies = [
        ('accounts', '0004_coadmin'),
    ]

    operations = [
        migrations.AddField(
            model_name='coadmin',
            name='permissions',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Console section keys this co-admin may open (see controlpanel.permissions).',
            ),
        ),
    ]

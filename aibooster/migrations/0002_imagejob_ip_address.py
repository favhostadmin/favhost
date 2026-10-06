from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='imagejob',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, db_index=True, null=True),
        ),
    ]

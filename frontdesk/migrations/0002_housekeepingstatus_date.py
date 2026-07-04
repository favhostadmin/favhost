import datetime

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontdesk', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='housekeepingstatus',
            name='date',
            field=models.DateField(default=datetime.date.today),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='housekeepingstatus',
            name='property',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hk_statuses', to='property.property'),
        ),
        migrations.AlterUniqueTogether(
            name='housekeepingstatus',
            unique_together={('property', 'date')},
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0003_listingreport'),
    ]

    operations = [
        migrations.AlterField(
            model_name='imagejob',
            name='status',
            field=models.CharField(
                choices=[('pending', 'Pending'), ('processing', 'Processing'), ('done', 'Done'),
                         ('failed', 'Failed'), ('held', 'Waiting for visitor')],
                db_index=True, default='pending', max_length=12),
        ),
    ]

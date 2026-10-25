from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0004_imagejob_held_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='boosterlead',
            name='feature',
            field=models.CharField(choices=[('image', 'Photo Enhancer'), ('report', 'Listing Audit')], max_length=10),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aibooster', '0006_payments'),
    ]

    operations = [
        migrations.AlterField(
            model_name='boosterlead',
            name='feature',
            field=models.CharField(choices=[('image', 'Photo Enhancer'), ('report', 'Listing Optimize')], max_length=10),
        ),
        migrations.AlterField(
            model_name='order',
            name='kind',
            field=models.CharField(choices=[('photos', 'Photo Enhancer'), ('report', 'Listing Optimize')], max_length=10),
        ),
    ]

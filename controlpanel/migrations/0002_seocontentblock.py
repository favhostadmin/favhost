from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controlpanel', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SeoContentBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100, unique=True)),
                ('section', models.CharField(db_index=True, max_length=50)),
                ('label', models.CharField(max_length=150)),
                ('field_type', models.CharField(choices=[('text', 'Text'), ('textarea', 'Textarea'), ('image', 'Image')], default='text', max_length=10)),
                ('text_value', models.TextField(blank=True, default='')),
                ('image', models.ImageField(blank=True, null=True, upload_to='seo/')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'SEO content block',
                'ordering': ['section', 'key'],
            },
        ),
    ]

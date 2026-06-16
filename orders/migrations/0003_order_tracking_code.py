from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_order_document'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='tracking_code',
            field=models.CharField(
                blank=True,
                max_length=12,
                null=True,
                unique=True,
                verbose_name='کد پیگیری',
            ),
        ),
    ]

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='KYCProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('national_id', models.CharField(blank=True, max_length=20, null=True, unique=True, verbose_name='کد ملی', help_text='کد ملی ۱۰ رقمی بدون خط تیره.')),
                ('date_of_birth', models.DateField(blank=True, null=True, verbose_name='تاریخ تولد')),
                ('status', models.CharField(choices=[('pending', 'در انتظار بررسی'), ('approved', 'تأیید شده'), ('rejected', 'رد شده')], db_index=True, default='pending', max_length=10, verbose_name='وضعیت')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخرین ویرایش')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='kyc_profile', to=settings.AUTH_USER_MODEL, verbose_name='کاربر')),
            ],
            options={
                'verbose_name': 'پروفایل KYC',
                'verbose_name_plural': 'پروفایل‌های KYC',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='kycprofile',
            index=models.Index(fields=['status', 'created_at'], name='kyc_status_created_idx'),
        ),
    ]

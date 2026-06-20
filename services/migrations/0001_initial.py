import django.db.models.deletion
import orders.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orders', '0005_order_workflow'),
    ]

    operations = [

        migrations.CreateModel(
            name='ServiceCategory',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',        models.CharField(max_length=200, verbose_name='نام دسته‌بندی')),
                ('slug',        models.SlugField(allow_unicode=True, max_length=200, unique=True, verbose_name='اسلاگ')),
                ('icon',        models.CharField(blank=True, max_length=100, verbose_name='آیکون', help_text='نام آیکون Bootstrap Icons — مثال: bi-globe')),
                ('description', models.TextField(blank=True, verbose_name='توضیحات')),
                ('is_active',   models.BooleanField(default=True, verbose_name='فعال')),
                ('sort_order',  models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')),
                ('created_at',  models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')),
            ],
            options={
                'verbose_name':        'دسته‌بندی سرویس',
                'verbose_name_plural': 'دسته‌بندی‌های سرویس',
                'ordering':            ['sort_order', 'name'],
            },
        ),

        migrations.CreateModel(
            name='Service',
            fields=[
                ('id',                models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',              models.CharField(max_length=200, verbose_name='نام سرویس')),
                ('slug',              models.SlugField(allow_unicode=True, max_length=200, unique=True, verbose_name='اسلاگ')),
                ('short_description', models.TextField(blank=True, verbose_name='توضیح کوتاه')),
                ('description',       models.TextField(blank=True, verbose_name='توضیح کامل')),
                ('icon',              models.CharField(blank=True, max_length=100, verbose_name='آیکون', help_text='نام آیکون Bootstrap Icons — مثال: bi-mortarboard-fill')),
                ('is_active',         models.BooleanField(default=True, verbose_name='فعال')),
                ('requires_kyc',      models.BooleanField(default=True, verbose_name='نیاز به احراز هویت')),
                ('requires_payment',  models.BooleanField(default=False, verbose_name='نیاز به پرداخت')),
                ('base_price',        models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='قیمت پایه')),
                ('currency',          models.CharField(blank=True, default='USD', max_length=10, verbose_name='ارز')),
                ('sort_order',        models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')),
                ('created_at',        models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')),
                ('category',          models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='services',
                    to='services.servicecategory',
                    verbose_name='دسته‌بندی',
                )),
            ],
            options={
                'verbose_name':        'سرویس',
                'verbose_name_plural': 'سرویس‌ها',
                'ordering':            ['sort_order', 'name'],
            },
        ),

        migrations.CreateModel(
            name='ServiceField',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label',        models.CharField(max_length=200, verbose_name='عنوان فیلد')),
                ('field_name',   models.SlugField(max_length=100, verbose_name='نام فنی فیلد', help_text='شناسه‌ای کوتاه و بدون فاصله — مثال: university_name')),
                ('field_type',   models.CharField(
                    choices=[
                        ('text', 'متن کوتاه'), ('textarea', 'متن بلند'),
                        ('number', 'عدد'), ('email', 'ایمیل'),
                        ('file', 'فایل (PDF / تصویر)'), ('select', 'انتخاب از لیست'),
                        ('date', 'تاریخ'), ('url', 'آدرس وب'),
                    ],
                    default='text', max_length=20, verbose_name='نوع فیلد',
                )),
                ('placeholder',   models.CharField(blank=True, max_length=300, verbose_name='متن راهنما (placeholder)')),
                ('help_text',     models.CharField(blank=True, max_length=500, verbose_name='راهنمای زیر فیلد')),
                ('is_required',   models.BooleanField(default=True, verbose_name='الزامی')),
                ('sort_order',    models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')),
                ('choices_json',  models.TextField(blank=True, verbose_name='گزینه‌های انتخابی (JSON)', help_text='فقط برای نوع «انتخاب از لیست». آرایه JSON — مثال: ["گزینه ۱", "گزینه ۲", "گزینه ۳"]')),
                ('service',       models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fields',
                    to='services.service',
                    verbose_name='سرویس',
                )),
            ],
            options={
                'verbose_name':        'فیلد سرویس',
                'verbose_name_plural': 'فیلدهای سرویس',
                'ordering':            ['sort_order', 'id'],
            },
        ),

        migrations.AddConstraint(
            model_name='servicefield',
            constraint=models.UniqueConstraint(
                fields=['service', 'field_name'],
                name='unique_service_field_name',
            ),
        ),

        migrations.CreateModel(
            name='OrderFieldValue',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value_text',    models.TextField(blank=True, verbose_name='مقدار متنی')),
                ('value_file',    models.FileField(
                    blank=True, null=True,
                    storage=orders.storage.PrivateFileSystemStorage(),
                    upload_to='services/submissions/%Y/%m/',
                    verbose_name='فایل بارگذاری‌شده',
                )),
                ('created_at',    models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت')),
                ('order',         models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='field_values',
                    to='orders.order',
                    verbose_name='سفارش',
                )),
                ('service_field', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='submitted_values',
                    to='services.servicefield',
                    verbose_name='فیلد سرویس',
                )),
            ],
            options={
                'verbose_name':        'مقدار فیلد سفارش',
                'verbose_name_plural': 'مقادیر فیلدهای سفارش',
                'ordering':            ['service_field__sort_order', 'service_field__id'],
            },
        ),
    ]

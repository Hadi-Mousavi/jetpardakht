import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # Required for PermissionsMixin M2M to auth.Group and auth.Permission
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID',
                )),
                # AbstractBaseUser fields
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(
                    blank=True,
                    null=True,
                    verbose_name='last login',
                )),
                # PermissionsMixin field
                ('is_superuser', models.BooleanField(
                    default=False,
                    help_text=(
                        'Designates that this user has all permissions '
                        'without explicitly assigning them.'
                    ),
                    verbose_name='superuser status',
                )),
                # JetPay24 identity fields
                ('email', models.EmailField(
                    max_length=254,
                    unique=True,
                    verbose_name='ایمیل',
                )),
                ('phone', models.CharField(
                    blank=True,
                    max_length=20,
                    null=True,
                    unique=True,
                    verbose_name='شماره موبایل',
                )),
                ('first_name', models.CharField(max_length=60, verbose_name='نام')),
                ('last_name', models.CharField(max_length=60, verbose_name='نام خانوادگی')),
                # Access control
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='غیرفعال کردن به جای حذف کاربر.',
                    verbose_name='فعال',
                )),
                ('is_staff', models.BooleanField(
                    default=False,
                    help_text='دسترسی به پنل مدیریت.',
                    verbose_name='کارمند',
                )),
                # Verification flags
                ('is_email_verified', models.BooleanField(
                    default=False,
                    verbose_name='ایمیل تأیید شده',
                )),
                ('is_phone_verified', models.BooleanField(
                    default=False,
                    verbose_name='موبایل تأیید شده',
                )),
                # Timestamps
                ('created_at', models.DateTimeField(
                    auto_now_add=True,
                    verbose_name='تاریخ ثبت',
                )),
                ('updated_at', models.DateTimeField(
                    auto_now=True,
                    verbose_name='آخرین ویرایش',
                )),
                # PermissionsMixin M2M relations
                ('groups', models.ManyToManyField(
                    blank=True,
                    help_text=(
                        'The groups this user belongs to. A user will get all '
                        'permissions granted to each of their groups.'
                    ),
                    related_name='user_set',
                    related_query_name='user',
                    to='auth.group',
                    verbose_name='groups',
                )),
                ('user_permissions', models.ManyToManyField(
                    blank=True,
                    help_text='Specific permissions for this user.',
                    related_name='user_set',
                    related_query_name='user',
                    to='auth.permission',
                    verbose_name='user permissions',
                )),
            ],
            options={
                'verbose_name': 'کاربر',
                'verbose_name_plural': 'کاربران',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='OTPCode',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID',
                )),
                ('phone', models.CharField(max_length=20, verbose_name='شماره موبایل')),
                ('code_hash', models.CharField(max_length=128, verbose_name='کد هش‌شده')),
                ('purpose', models.CharField(
                    choices=[
                        ('LOGIN', 'ورود'),
                        ('REGISTER', 'ثبت‌نام'),
                        ('PHONE_VERIFY', 'تأیید موبایل'),
                        ('PASSWORD_RESET', 'بازیابی رمز عبور'),
                    ],
                    max_length=20,
                    verbose_name='هدف',
                )),
                ('created_at', models.DateTimeField(
                    auto_now_add=True,
                    verbose_name='تاریخ ایجاد',
                )),
                ('expires_at', models.DateTimeField(verbose_name='تاریخ انقضا')),
                ('consumed_at', models.DateTimeField(
                    blank=True,
                    null=True,
                    verbose_name='تاریخ استفاده',
                )),
                ('attempt_count', models.PositiveSmallIntegerField(
                    default=0,
                    verbose_name='تعداد تلاش',
                )),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='otp_codes',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='کاربر',
                )),
            ],
            options={
                'verbose_name': 'کد یکبار مصرف',
                'verbose_name_plural': 'کدهای یکبار مصرف',
            },
        ),
        migrations.AddIndex(
            model_name='otpcode',
            index=models.Index(
                fields=['phone', 'purpose'],
                name='accounts_otpcode_phone_purpose_idx',
            ),
        ),
    ]

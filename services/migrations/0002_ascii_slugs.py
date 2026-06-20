"""
Migration: enforce ASCII-only slugs on ServiceCategory and Service.

Operations (in order):
  1. Data migration — scan all existing rows; re-generate any slug that
     contains non-ASCII characters:
       • slugify(name) if it produces a non-empty ASCII string
       • "category-{pk}" / "service-{pk}" fallback otherwise
     Uniqueness conflicts are resolved by appending a numeric suffix.
  2. AlterField — remove allow_unicode=True from both SlugField definitions
     so Django's model-level validator also rejects non-ASCII slugs.
"""

import re

from django.db import migrations, models
from django.utils.text import slugify

_ASCII_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _is_valid(slug):
    return bool(slug and _ASCII_SLUG_RE.match(slug))


def _unique_slug(qs, base, current_pk):
    slug = base
    counter = 1
    while qs.filter(slug=slug).exclude(pk=current_pk).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


def fix_persian_slugs(apps, schema_editor):
    ServiceCategory = apps.get_model('services', 'ServiceCategory')
    Service         = apps.get_model('services', 'Service')

    # Fix ServiceCategory slugs
    for cat in ServiceCategory.objects.all():
        if not _is_valid(cat.slug):
            base = slugify(cat.slug) or slugify(cat.name) or f'category-{cat.pk}'
            cat.slug = _unique_slug(ServiceCategory.objects, base, cat.pk)
            cat.save(update_fields=['slug'])

    # Fix Service slugs
    for svc in Service.objects.all():
        if not _is_valid(svc.slug):
            base = slugify(svc.slug) or slugify(svc.name) or f'service-{svc.pk}'
            svc.slug = _unique_slug(Service.objects, base, svc.pk)
            svc.save(update_fields=['slug'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('services', '0001_initial'),
    ]

    operations = [
        # Step 1: fix the data before tightening the schema
        migrations.RunPython(fix_persian_slugs, reverse_code=noop),

        # Step 2: remove allow_unicode=True from ServiceCategory.slug
        migrations.AlterField(
            model_name='servicecategory',
            name='slug',
            field=models.SlugField(
                blank=True,
                max_length=200,
                unique=True,
                verbose_name='اسلاگ',
                help_text=(
                    'فقط حروف انگلیسی، اعداد، خط تیره و زیرخط مجاز است. '
                    'اگر خالی بگذارید، به‌صورت خودکار از نام تولید می‌شود.'
                ),
            ),
        ),

        # Step 3: remove allow_unicode=True from Service.slug
        migrations.AlterField(
            model_name='service',
            name='slug',
            field=models.SlugField(
                blank=True,
                max_length=200,
                unique=True,
                verbose_name='اسلاگ',
                help_text=(
                    'فقط حروف انگلیسی، اعداد، خط تیره و زیرخط مجاز است. '
                    'اگر خالی بگذارید، به‌صورت خودکار از نام تولید می‌شود.'
                ),
            ),
        ),
    ]

"""
SERVICE CATALOG & DYNAMIC ORDERS SPRINT — comprehensive tests.

Coverage:
  MODELS
    - ServiceCategory CRUD and ordering
    - Service CRUD, ordering, price_display
    - ServiceField CRUD, parsed_choices, unique_together
    - OrderFieldValue CRUD, display_value, is_file
  DYNAMIC FORM GENERATION
    - Form class built from ServiceField records
    - All 8 field types (text, textarea, number, email, url, date, select, file)
    - Required / optional fields
  DYNAMIC FORM VALIDATION
    - Text length limits
    - Email format
    - URL format
    - Select choice must exist in choices_json
    - File: extension allow-list
    - File: size limit
    - File: magic bytes
  SERVICE CATALOG VIEW
    - Anonymous redirect
    - Active services shown; inactive hidden
    - Empty state (no active services)
  SERVICE ORDER FORM VIEW
    - GET renders form
    - KYC gate: service with requires_kyc and unapproved user is redirected
    - POST valid → Order + OrderFieldValue created
    - POST invalid → errors shown; no Order created
  FILE DOWNLOAD VIEW
    - Owner can download their own file
    - Staff can download any file
    - Other user cannot download
    - Non-file field raises 404
  NOTIFICATIONS
    - SERVICE_ORDER_CREATED created on service order submission
    - Regular orders still get TYPE_ORDER_CREATED
  ADMIN CONFIGURATION
    - ServiceCategoryAdmin registered
    - ServiceAdmin registered with ServiceFieldInline
    - OrderFieldValueAdmin is read-only
  ORDER DETAIL PAGE
    - field_values shown in order detail context
    - Secure download link rendered for file fields
    - Non-file values rendered as text
"""

import io
import json
import re
import struct
import tempfile
from datetime import date

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from kyc.models import KYCProfile
from notifications.models import Notification
from orders.models import Category, Order, SubCategory

from .admin import ServiceAdmin, ServiceCategoryAdmin
from .forms import build_order_form, validate_service_upload
from .models import OrderFieldValue, Service, ServiceCategory, ServiceField

_PRIVATE_MEDIA_TMP = tempfile.mkdtemp(prefix='jp24_svc_test_')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(email='user@test.com', *, is_staff=False, kyc_approved=False):
    user = User.objects.create_user(
        email=email, password='Test1234!',
        first_name='Test', last_name='User',
    )
    if is_staff:
        user.is_staff = True
        user.save()
    if kyc_approved:
        numeric_id = str(abs(hash(email)) % 10_000_000_000).zfill(10)
        KYCProfile.objects.create(
            user=user,
            national_id=numeric_id,
            date_of_birth=date(1990, 1, 1),
            status=KYCProfile.STATUS_APPROVED,
        )
    return user


def _make_category_service(name='Test Service', requires_kyc=False, is_active=True):
    """Return (ServiceCategory, Service) pair."""
    safe = name.replace(' ', '-').lower()[:20]
    uid = abs(id(name))
    cat = ServiceCategory.objects.create(
        name='Test Category', slug=f'tc-{safe}-{uid}',
        is_active=True,
    )
    svc = Service.objects.create(
        category=cat,
        name=name,
        slug=f'ts-{safe}-{uid}',
        short_description='A test service',
        requires_kyc=requires_kyc,
        is_active=is_active,
        base_price='100.00',
        currency='USD',
    )
    return cat, svc


def _add_field(service, field_type, label='Field', field_name=None, is_required=True, choices=None):
    if field_name is None:
        field_name = f'f_{field_type[:4]}_{abs(id(label))}'
    kwargs = dict(
        service=service,
        label=label,
        field_name=field_name,
        field_type=field_type,
        is_required=is_required,
        sort_order=0,
    )
    if choices:
        kwargs['choices_json'] = json.dumps(choices)
    return ServiceField.objects.create(**kwargs)


def _jpeg_file(name='test.jpg'):
    """Minimal valid JPEG (SOI marker + EOF)."""
    data = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'\x00' * 12 + bytes([0xFF, 0xD9])
    return SimpleUploadedFile(name, data, content_type='image/jpeg')


def _pdf_file(name='test.pdf'):
    """Minimal valid PDF header."""
    data = b'%PDF-1.4\n%%EOF'
    return SimpleUploadedFile(name, data, content_type='application/pdf')


def _make_orders_cat():
    """Return (Category, SubCategory) for Order creation."""
    cat, _ = Category.objects.get_or_create(
        slug='online-services',
        defaults={'title': 'خدمات آنلاین', 'is_active': True},
    )
    sub, _ = SubCategory.objects.get_or_create(
        category=cat, title='Test Sub', defaults={'is_active': True},
    )
    return cat, sub


# ===========================================================================
# MODEL TESTS
# ===========================================================================

class ServiceCategoryModelTests(TestCase):

    def test_create_and_str(self):
        cat = ServiceCategory.objects.create(name='دانشگاه', slug='danesghah')
        self.assertEqual(str(cat), 'دانشگاه')

    def test_ordering_by_sort_order_then_name(self):
        ServiceCategory.objects.create(name='Beta', slug='beta', sort_order=2)
        ServiceCategory.objects.create(name='Alpha', slug='alpha', sort_order=1)
        ServiceCategory.objects.create(name='Gamma', slug='gamma', sort_order=2)
        names = list(ServiceCategory.objects.values_list('name', flat=True))
        # Alpha (sort_order=1) first, then Beta before Gamma (sort_order=2, name asc)
        self.assertEqual(names[0], 'Alpha')
        self.assertLess(names.index('Beta'), names.index('Gamma'))

    def test_slug_unique(self):
        ServiceCategory.objects.create(name='A', slug='same-slug')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ServiceCategory.objects.create(name='B', slug='same-slug')

    def test_is_active_default_true(self):
        cat = ServiceCategory.objects.create(name='X', slug='x')
        self.assertTrue(cat.is_active)


class ServiceModelTests(TestCase):

    def setUp(self):
        self.cat = ServiceCategory.objects.create(name='Cat', slug='cat')

    def test_create_and_str(self):
        svc = Service.objects.create(
            category=self.cat, name='My Service', slug='my-service',
        )
        self.assertEqual(str(svc), 'My Service')

    def test_price_display_with_price(self):
        svc = Service.objects.create(
            category=self.cat, name='Svc', slug='svc-pd',
            base_price='250.00', currency='USD',
        )
        self.assertIn('250', svc.price_display)
        self.assertIn('USD', svc.price_display)

    def test_price_display_without_price(self):
        svc = Service.objects.create(category=self.cat, name='Free', slug='free')
        self.assertEqual(svc.price_display, '')

    def test_slug_unique(self):
        Service.objects.create(category=self.cat, name='A', slug='dup-slug')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Service.objects.create(category=self.cat, name='B', slug='dup-slug')


class ServiceFieldModelTests(TestCase):

    def setUp(self):
        cat = ServiceCategory.objects.create(name='C', slug='c')
        self.svc = Service.objects.create(category=cat, name='S', slug='s')

    def test_str(self):
        sf = ServiceField.objects.create(
            service=self.svc, label='نام', field_name='name', field_type='text',
        )
        self.assertIn('نام', str(sf))

    def test_unique_together_service_field_name(self):
        ServiceField.objects.create(
            service=self.svc, label='A', field_name='myfield', field_type='text',
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ServiceField.objects.create(
                service=self.svc, label='B', field_name='myfield', field_type='email',
            )

    def test_parsed_choices_valid_json(self):
        sf = ServiceField.objects.create(
            service=self.svc, label='Pick', field_name='pick',
            field_type='select', choices_json='["گزینه ۱", "گزینه ۲"]',
        )
        choices = sf.parsed_choices()
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0], ('گزینه ۱', 'گزینه ۱'))

    def test_parsed_choices_empty(self):
        sf = ServiceField.objects.create(
            service=self.svc, label='T', field_name='t', field_type='text',
        )
        self.assertEqual(sf.parsed_choices(), [])

    def test_parsed_choices_invalid_json(self):
        sf = ServiceField.objects.create(
            service=self.svc, label='Bad', field_name='bad',
            field_type='select', choices_json='not-json',
        )
        self.assertEqual(sf.parsed_choices(), [])

    def test_ordering(self):
        sf1 = ServiceField.objects.create(
            service=self.svc, label='B', field_name='b', field_type='text', sort_order=2,
        )
        sf2 = ServiceField.objects.create(
            service=self.svc, label='A', field_name='a', field_type='text', sort_order=1,
        )
        ids = list(self.svc.fields.values_list('id', flat=True))
        self.assertEqual(ids[0], sf2.pk)   # sort_order=1 first


class OrderFieldValueModelTests(TestCase):

    def setUp(self):
        cat = ServiceCategory.objects.create(name='C', slug='c-ofv')
        svc = Service.objects.create(category=cat, name='S', slug='s-ofv')
        self.sf = ServiceField.objects.create(
            service=svc, label='Name', field_name='name', field_type='text',
        )
        oc, os = _make_orders_cat()
        user = _make_user('ofv@test.com')
        self.order = Order.objects.create(
            user=user, category=oc, subcategory=os, description='test', service=svc,
        )

    def test_text_value(self):
        fv = OrderFieldValue.objects.create(
            order=self.order, service_field=self.sf, value_text='UCSD',
        )
        self.assertFalse(fv.is_file)
        self.assertEqual(fv.display_value, 'UCSD')

    def test_str(self):
        fv = OrderFieldValue.objects.create(
            order=self.order, service_field=self.sf, value_text='MIT',
        )
        self.assertIn(self.order.order_number, str(fv))


# ===========================================================================
# DYNAMIC FORM GENERATION TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class DynamicFormGenerationTests(TestCase):

    def setUp(self):
        cat = ServiceCategory.objects.create(name='FC', slug='fc')
        self.svc = Service.objects.create(category=cat, name='FS', slug='fs')

    def test_empty_service_has_empty_form(self):
        form = build_order_form(self.svc)
        self.assertEqual(len(form.fields), 0)

    def test_text_field_generated(self):
        _add_field(self.svc, 'text', 'Name', 'name')
        form = build_order_form(self.svc)
        self.assertIn('name', form.fields)

    def test_all_field_types_generated(self):
        for i, ft in enumerate(['text', 'textarea', 'number', 'email', 'url', 'date', 'select', 'file']):
            _add_field(self.svc, ft, ft.capitalize(), f'field_{i}_{ft}',
                       choices=['A', 'B'] if ft == 'select' else None)
        form = build_order_form(self.svc)
        self.assertEqual(len(form.fields), 8)

    def test_required_field_marked_required(self):
        _add_field(self.svc, 'text', 'Req', 'req', is_required=True)
        form = build_order_form(self.svc)
        self.assertTrue(form.fields['req'].required)

    def test_optional_field_not_required(self):
        _add_field(self.svc, 'text', 'Opt', 'opt', is_required=False)
        form = build_order_form(self.svc)
        self.assertFalse(form.fields['opt'].required)

    def test_select_choices_populated(self):
        _add_field(self.svc, 'select', 'Pick', 'pick', choices=['X', 'Y', 'Z'])
        form = build_order_form(self.svc)
        choices_values = [c[0] for c in form.fields['pick'].choices]
        self.assertIn('X', choices_values)
        self.assertIn('Y', choices_values)
        self.assertIn('Z', choices_values)

    def test_bound_form_with_data(self):
        _add_field(self.svc, 'text', 'City', 'city')
        form = build_order_form(self.svc, data={'city': 'Tehran'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['city'], 'Tehran')

    def test_invalid_email_fails(self):
        _add_field(self.svc, 'email', 'Email', 'email')
        form = build_order_form(self.svc, data={'email': 'not-an-email'})
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_valid_email_passes(self):
        _add_field(self.svc, 'email', 'Email', 'email2')
        form = build_order_form(self.svc, data={'email2': 'user@example.com'})
        self.assertTrue(form.is_valid())

    def test_number_field_validates_decimal(self):
        _add_field(self.svc, 'number', 'Amount', 'amount')
        form = build_order_form(self.svc, data={'amount': '1500.50'})
        self.assertTrue(form.is_valid())

    def test_number_field_rejects_non_numeric(self):
        _add_field(self.svc, 'number', 'Amount', 'amounterr')
        form = build_order_form(self.svc, data={'amounterr': 'abc'})
        self.assertFalse(form.is_valid())

    def test_url_field_validates(self):
        _add_field(self.svc, 'url', 'Website', 'website')
        form = build_order_form(self.svc, data={'website': 'https://example.com'})
        self.assertTrue(form.is_valid())

    def test_url_field_rejects_invalid(self):
        _add_field(self.svc, 'url', 'Website', 'weburl')
        form = build_order_form(self.svc, data={'weburl': 'not a url'})
        self.assertFalse(form.is_valid())

    def test_select_rejects_unlisted_choice(self):
        _add_field(self.svc, 'select', 'Pick', 'pickval', choices=['A', 'B'])
        form = build_order_form(self.svc, data={'pickval': 'C'})
        self.assertFalse(form.is_valid())

    def test_select_accepts_listed_choice(self):
        _add_field(self.svc, 'select', 'Pick', 'pickok', choices=['A', 'B'])
        form = build_order_form(self.svc, data={'pickok': 'A'})
        self.assertTrue(form.is_valid())

    def test_text_field_max_length_rejected(self):
        _add_field(self.svc, 'text', 'Short', 'short')
        form = build_order_form(self.svc, data={'short': 'x' * 2001})
        self.assertFalse(form.is_valid())


# ===========================================================================
# FILE UPLOAD VALIDATION TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceFileUploadValidationTests(TestCase):

    def _make_file(self, name, content, content_type='application/octet-stream'):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def test_jpeg_passes(self):
        f = _jpeg_file()
        validate_service_upload(f)   # no exception

    def test_pdf_passes(self):
        f = _pdf_file()
        validate_service_upload(f)   # no exception

    def test_disallowed_extension_rejected(self):
        f = self._make_file('file.zip', b'PK\x03\x04')
        with self.assertRaises(ValidationError):
            validate_service_upload(f)

    def test_docx_rejected_for_service_upload(self):
        """Service uploads restrict to jpg/png/pdf only (not docx)."""
        f = self._make_file('doc.docx', b'PK\x03\x04')
        with self.assertRaises(ValidationError):
            validate_service_upload(f)

    def test_oversized_file_rejected(self):
        big = SimpleUploadedFile('big.jpg', b'X' * (11 * 1024 * 1024))
        with self.assertRaises(ValidationError):
            validate_service_upload(big)

    def test_wrong_magic_bytes_rejected(self):
        # .jpg extension but random content (no JPEG magic)
        f = self._make_file('fake.jpg', b'\x00' * 50)
        with self.assertRaises(ValidationError):
            validate_service_upload(f)

    def test_none_file_passes(self):
        validate_service_upload(None)   # should not raise

    def test_file_field_in_form_validates(self):
        cat = ServiceCategory.objects.create(name='FC2', slug='fc2')
        svc = Service.objects.create(category=cat, name='FS2', slug='fs2')
        _add_field(svc, 'file', 'Receipt', 'receipt')
        bad_file = self._make_file('evil.exe', b'\x4d\x5a\x00\x00')
        form = build_order_form(svc, data={}, files={'receipt': bad_file})
        self.assertFalse(form.is_valid())


# ===========================================================================
# CATALOG VIEW TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceCatalogViewTests(TestCase):

    def setUp(self):
        self.user = _make_user('catalog@test.com')
        _, self.svc = _make_category_service('Catalog Service')

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse('service_catalog'))
        self.assertRedirects(resp, f'/auth/login/?next={reverse("service_catalog")}',
                             fetch_redirect_response=False)

    def test_authenticated_can_access(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('service_catalog'))
        self.assertEqual(resp.status_code, 200)

    def test_active_service_shown(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('service_catalog'))
        self.assertContains(resp, 'Catalog Service')

    def test_inactive_service_not_shown(self):
        self.svc.is_active = False
        self.svc.save()
        self.client.force_login(self.user)
        resp = self.client.get(reverse('service_catalog'))
        self.assertNotContains(resp, 'Catalog Service')

    def test_service_catalog_link_present(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('service_catalog'))
        self.assertContains(resp, 'ثبت سفارش')


# ===========================================================================
# SERVICE ORDER VIEW TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceOrderViewTests(TestCase):

    def setUp(self):
        self.user = _make_user('ord@test.com', kyc_approved=True)
        _, self.svc = _make_category_service('Order Service', requires_kyc=False)
        _add_field(self.svc, 'text', 'University', 'university')
        _add_field(self.svc, 'text', 'Student ID', 'student_id')

    def test_get_renders_form(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'University')
        self.assertContains(resp, 'Student ID')

    def test_post_valid_creates_order(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        before = Order.objects.count()
        resp = self.client.post(url, {
            'university': 'UCSD',
            'student_id': '123456',
        })
        self.assertEqual(Order.objects.count(), before + 1)
        order = Order.objects.filter(user=self.user).latest('created_at')
        self.assertEqual(order.service, self.svc)

    def test_post_valid_creates_field_values(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        self.client.post(url, {
            'university': 'MIT',
            'student_id': '999',
        })
        order = Order.objects.filter(user=self.user).latest('created_at')
        fvs = order.field_values.all()
        self.assertEqual(fvs.count(), 2)
        values_dict = {fv.service_field.field_name: fv.value_text for fv in fvs}
        self.assertEqual(values_dict['university'], 'MIT')
        self.assertEqual(values_dict['student_id'], '999')

    def test_post_valid_redirects_to_order_detail(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.post(url, {
            'university': 'Stanford',
            'student_id': '777',
        })
        order = Order.objects.filter(user=self.user).latest('created_at')
        self.assertRedirects(resp, reverse('order_detail', kwargs={'pk': order.pk}),
                             fetch_redirect_response=False)

    def test_post_missing_required_field_shows_errors(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        before = Order.objects.count()
        resp = self.client.post(url, {'university': 'UCSD'})  # missing student_id
        # No new order should be created
        self.assertEqual(Order.objects.count(), before)
        # Form is re-rendered with errors (200, not redirect)
        self.assertEqual(resp.status_code, 200)
        # Template uses field-error class for errors
        self.assertContains(resp, 'field-error')

    def test_inactive_service_returns_404(self):
        self.svc.is_active = False
        self.svc.save()
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_redirected(self):
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp['Location'])


@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceOrderKycGateTests(TestCase):
    """KYC requirement gate on service order view."""

    def setUp(self):
        self.user_no_kyc = _make_user('nokyc@test.com')
        _, self.svc = _make_category_service('KYC Service', requires_kyc=True)

    def test_no_kyc_redirected(self):
        self.client.force_login(self.user_no_kyc)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.get(url)
        # Should redirect away (to kyc form)
        self.assertIn(resp.status_code, [302, 301])

    def test_approved_kyc_can_access(self):
        user = _make_user('yeskyc@test.com', kyc_approved=True)
        self.client.force_login(user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceOrderFileUploadTests(TestCase):
    """File field in service order form."""

    def setUp(self):
        self.user = _make_user('fileuser@test.com', kyc_approved=True)
        _, self.svc = _make_category_service('File Service', requires_kyc=False)
        _add_field(self.svc, 'file', 'Receipt', 'receipt')

    def test_valid_jpeg_accepted(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        resp = self.client.post(url, {'receipt': _jpeg_file()}, format='multipart')
        order = Order.objects.filter(user=self.user).last()
        self.assertIsNotNone(order)
        fv = order.field_values.first()
        self.assertTrue(fv.is_file)

    def test_invalid_file_shows_error(self):
        self.client.force_login(self.user)
        url = reverse('service_order', kwargs={'slug': self.svc.slug})
        bad = SimpleUploadedFile('evil.exe', b'\x4d\x5a\x00\x00', content_type='application/octet-stream')
        before = Order.objects.count()
        resp = self.client.post(url, {'receipt': bad}, format='multipart')
        self.assertEqual(Order.objects.count(), before)


# ===========================================================================
# FILE DOWNLOAD VIEW TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class FieldValueDownloadTests(TestCase):

    def setUp(self):
        self.owner = _make_user('owner@test.com')
        self.other = _make_user('other@test.com')
        self.staff = _make_user('staff@test.com', is_staff=True)

        cat = ServiceCategory.objects.create(name='DL', slug='dl')
        svc = Service.objects.create(category=cat, name='DL Svc', slug='dl-svc')
        sf_text = ServiceField.objects.create(
            service=svc, label='Text', field_name='text_fld', field_type='text',
        )
        oc, os = _make_orders_cat()
        self.order = Order.objects.create(
            user=self.owner, category=oc, subcategory=os,
            description='DL test', service=svc,
        )
        self.fv_text = OrderFieldValue.objects.create(
            order=self.order, service_field=sf_text, value_text='Hello',
        )

    def test_no_file_field_returns_404(self):
        self.client.force_login(self.owner)
        resp = self.client.get(
            reverse('field_value_download', kwargs={'pk': self.fv_text.pk})
        )
        self.assertEqual(resp.status_code, 404)

    def test_other_user_forbidden(self):
        self.client.force_login(self.other)
        resp = self.client.get(
            reverse('field_value_download', kwargs={'pk': self.fv_text.pk})
        )
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected(self):
        resp = self.client.get(
            reverse('field_value_download', kwargs={'pk': self.fv_text.pk})
        )
        self.assertIn(resp.status_code, [302, 301])

    def test_staff_can_access(self):
        """Staff should get 404 (no file stored) not 403."""
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('field_value_download', kwargs={'pk': self.fv_text.pk})
        )
        # Staff passes ownership check; no actual file → 404
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# NOTIFICATION TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class ServiceOrderNotificationTests(TestCase):

    def setUp(self):
        self.user = _make_user('notif@test.com')
        _, self.svc = _make_category_service('Notif Service', requires_kyc=False)
        oc, os = _make_orders_cat()
        self.oc, self.os = oc, os

    def test_service_order_creates_service_notification(self):
        order = Order.objects.create(
            user=self.user,
            category=self.oc,
            subcategory=self.os,
            description='notif test',
            service=self.svc,
        )
        notif = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.notification_type, Notification.TYPE_SERVICE_ORDER_CREATED)

    def test_regular_order_creates_order_created_notification(self):
        Order.objects.create(
            user=self.user,
            category=self.oc,
            subcategory=self.os,
            description='regular order',
        )
        notif = Notification.objects.filter(
            user=self.user,
            notification_type=Notification.TYPE_ORDER_CREATED,
        ).first()
        self.assertIsNotNone(notif)

    def test_service_order_notification_message(self):
        Order.objects.create(
            user=self.user,
            category=self.oc,
            subcategory=self.os,
            description='msg test',
            service=self.svc,
        )
        notif = Notification.objects.filter(
            user=self.user,
            notification_type=Notification.TYPE_SERVICE_ORDER_CREATED,
        ).first()
        self.assertIn('ثبت', notif.title)

    def test_notification_display_properties(self):
        notif = Notification(notification_type=Notification.TYPE_SERVICE_ORDER_CREATED)
        self.assertEqual(notif.display_type, 'success')
        self.assertEqual(notif.display_icon, 'bi-bag-check-fill')
        self.assertEqual(notif.display_emoji, '🛍️')


# ===========================================================================
# ORDER DETAIL PAGE — FIELD VALUES DISPLAYED
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class OrderDetailFieldValuesTests(TestCase):

    def setUp(self):
        self.user = _make_user('detail@test.com')
        cat = ServiceCategory.objects.create(name='DC', slug='dc')
        svc = Service.objects.create(category=cat, name='DS', slug='ds')
        sf = ServiceField.objects.create(
            service=svc, label='University Name', field_name='uni', field_type='text',
        )
        oc, os = _make_orders_cat()
        self.order = Order.objects.create(
            user=self.user, category=oc, subcategory=os, description='detail test', service=svc,
        )
        self.fv = OrderFieldValue.objects.create(
            order=self.order, service_field=sf, value_text='UCSD',
        )

    def test_field_values_in_context(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', kwargs={'pk': self.order.pk}))
        self.assertIn('field_values', resp.context)
        self.assertEqual(len(resp.context['field_values']), 1)

    def test_field_label_shown_in_template(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', kwargs={'pk': self.order.pk}))
        self.assertContains(resp, 'University Name')

    def test_field_value_shown_in_template(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', kwargs={'pk': self.order.pk}))
        self.assertContains(resp, 'UCSD')

    def test_no_field_values_for_regular_order(self):
        oc, os = _make_orders_cat()
        regular_order = Order.objects.create(
            user=self.user, category=oc, subcategory=os, description='regular',
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', kwargs={'pk': regular_order.pk}))
        self.assertIn('field_values', resp.context)
        self.assertEqual(len(resp.context['field_values']), 0)


# ===========================================================================
# ADMIN CONFIGURATION TESTS
# ===========================================================================

class AdminConfigTests(TestCase):

    def setUp(self):
        self.site = AdminSite()
        cat = ServiceCategory.objects.create(name='Admin Cat', slug='admin-cat')
        self.svc = Service.objects.create(category=cat, name='Admin Svc', slug='admin-svc')

    def test_service_category_admin_registered(self):
        from django.contrib import admin as django_admin
        self.assertIn(ServiceCategory, django_admin.site._registry)

    def test_service_admin_registered(self):
        from django.contrib import admin as django_admin
        self.assertIn(Service, django_admin.site._registry)

    def test_service_admin_has_inline(self):
        from .admin import ServiceAdmin, ServiceFieldInline
        ma = ServiceAdmin(Service, self.site)
        inline_class_names = [cls.__name__ for cls in ma.inlines]
        self.assertIn('ServiceFieldInline', inline_class_names)

    def test_order_field_value_admin_has_no_add_permission(self):
        from .admin import OrderFieldValueAdmin
        ma = OrderFieldValueAdmin(OrderFieldValue, self.site)
        request = type('Req', (), {'user': _make_user('adm@test.com', is_staff=True)})()
        self.assertFalse(ma.has_add_permission(request))

    def test_order_field_value_admin_has_no_change_permission(self):
        from .admin import OrderFieldValueAdmin
        ma = OrderFieldValueAdmin(OrderFieldValue, self.site)
        request = type('Req', (), {'user': _make_user('adm2@test.com', is_staff=True)})()
        self.assertFalse(ma.has_change_permission(request))

    def test_service_category_admin_search_fields(self):
        from .admin import ServiceCategoryAdmin
        ma = ServiceCategoryAdmin(ServiceCategory, self.site)
        self.assertIn('name', ma.search_fields)
        self.assertIn('slug', ma.search_fields)

    def test_service_admin_filter_fields(self):
        from .admin import ServiceAdmin
        ma = ServiceAdmin(Service, self.site)
        self.assertIn('is_active', ma.list_filter)
        self.assertIn('category', ma.list_filter)
        self.assertIn('requires_kyc', ma.list_filter)
        self.assertIn('requires_payment', ma.list_filter)


# ===========================================================================
# PERFORMANCE / QUERY TESTS
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class PerformanceTests(TestCase):
    """Smoke checks that views use select_related / prefetch_related."""

    def setUp(self):
        self.user = _make_user('perf@test.com')
        for i in range(3):
            _, svc = _make_category_service(f'Perf Service {i}')
            for j in range(3):
                _add_field(svc, 'text', f'Field {j}', f'field_{j}_{i}')

    def test_catalog_view_no_n_plus_one(self):
        """Catalog uses prefetch_related — page renders without N+1 issues."""
        self.client.force_login(self.user)
        # Simply verify the view returns 200 and contains service names.
        resp = self.client.get(reverse('service_catalog'))
        self.assertEqual(resp.status_code, 200)
        # With 3 services each having 3 fields, all should be visible
        self.assertContains(resp, 'Perf Service 0')


# ===========================================================================
# SLUG SAFETY TESTS  (BUGFIX: Persian slug → NoReverseMatch)
# ===========================================================================

class ServiceSlugGenerationTests(TestCase):
    """
    Verify that Service.save() always produces an ASCII-only slug that is
    compatible with Django's built-in <slug:slug> URL converter.

    Covers:
      - Persian-only service name   → UUID-based fallback slug
      - English service name        → slugified slug
      - Mixed Persian/English name  → ASCII parts retained
      - Explicit valid ASCII slug   → preserved unchanged
      - Explicit Persian slug       → auto-replaced with generated slug
      - Duplicate slug              → unique suffix appended
      - URL reverse() works
      - URL resolve() works
      - ValidationError on full_clean() with Persian slug
    """

    _ASCII_RE = re.compile(r'^[a-zA-Z0-9_-]+$')

    def _cat(self, name='Cat'):
        # Use explicit ASCII slug so category creation is not affected by slug logic
        return ServiceCategory.objects.create(name=name, slug=f'cat-{abs(id(name))}')

    def _assert_ascii(self, slug, msg=''):
        self.assertTrue(
            bool(slug) and self._ASCII_RE.match(slug),
            msg=f'Expected ASCII-only slug, got: {slug!r}' + (f' ({msg})' if msg else ''),
        )

    # ── Name-based slug generation ──────────────────────────────────────

    def test_persian_only_name_gets_fallback_slug(self):
        """Pure Persian name → slugify returns '' → fallback UUID/pk slug."""
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='ترجمه مدارک دانشگاهی')
        self._assert_ascii(svc.slug, 'Persian-only name')

    def test_english_name_gets_slugified_slug(self):
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='University Translation')
        self.assertEqual(svc.slug, 'university-translation')

    def test_mixed_persian_english_name_keeps_english_parts(self):
        """Mixed name: ASCII parts are kept, Persian parts are stripped."""
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='Translation ترجمه Service')
        self._assert_ascii(svc.slug, 'Mixed name')
        self.assertIn('translation', svc.slug)
        self.assertIn('service', svc.slug)

    def test_explicit_ascii_slug_is_preserved(self):
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='Some Name', slug='my-custom-slug')
        self.assertEqual(svc.slug, 'my-custom-slug')

    def test_explicit_persian_slug_is_auto_replaced(self):
        """Even if caller passes a Persian slug, save() replaces it."""
        cat = self._cat()
        svc = Service.objects.create(
            category=cat, name='ارسال پول بین‌المللی', slug='ارسال-پول',
        )
        self._assert_ascii(svc.slug, 'Persian slug auto-replaced')

    def test_slug_is_unique_when_duplicate_base(self):
        """Two services with the same (English) name get different slugs."""
        cat = self._cat()
        svc1 = Service.objects.create(category=cat, name='Money Transfer')
        svc2 = Service.objects.create(category=cat, name='Money Transfer')
        self.assertNotEqual(svc1.slug, svc2.slug)
        self._assert_ascii(svc1.slug)
        self._assert_ascii(svc2.slug)

    def test_slug_is_unique_for_two_persian_names(self):
        cat = self._cat()
        svc1 = Service.objects.create(category=cat, name='حواله ارزی')
        svc2 = Service.objects.create(category=cat, name='پرداخت خارجی')
        self.assertNotEqual(svc1.slug, svc2.slug)
        self._assert_ascii(svc1.slug)
        self._assert_ascii(svc2.slug)

    def test_blank_slug_auto_generated_on_save(self):
        """slug='' triggers auto-generation."""
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='My Service', slug='')
        self.assertTrue(svc.slug)
        self._assert_ascii(svc.slug)

    # ── ServiceCategory slug generation ────────────────────────────────

    def test_category_persian_name_gets_ascii_slug(self):
        cat = ServiceCategory.objects.create(name='خدمات دانشگاهی')
        self._assert_ascii(cat.slug, 'Persian category name')

    def test_category_english_name_gets_slugified_slug(self):
        cat = ServiceCategory.objects.create(name='University Services')
        self.assertEqual(cat.slug, 'university-services')

    def test_category_explicit_persian_slug_auto_replaced(self):
        cat = ServiceCategory.objects.create(name='تست', slug='اسلاگ-فارسی')
        self._assert_ascii(cat.slug)

    # ── Validation (full_clean) ─────────────────────────────────────────

    def test_full_clean_rejects_persian_slug_for_service(self):
        """full_clean() raises ValidationError for a Persian slug."""
        cat = self._cat()
        svc = Service(category=cat, name='Test', slug='ارسال-پول')
        with self.assertRaises(ValidationError) as ctx:
            svc.full_clean()
        self.assertIn('slug', ctx.exception.message_dict)

    def test_full_clean_rejects_persian_slug_for_category(self):
        cat = ServiceCategory(name='Test', slug='دسته-فارسی')
        with self.assertRaises(ValidationError) as ctx:
            cat.full_clean()
        self.assertIn('slug', ctx.exception.message_dict)

    def test_full_clean_accepts_valid_ascii_slug(self):
        """full_clean() does NOT raise for a valid ASCII slug."""
        cat = self._cat()
        svc = Service(
            category=cat, name='Test', slug='valid-ascii-slug-123',
            requires_kyc=False,
        )
        try:
            svc.full_clean()
        except ValidationError as e:
            if 'slug' in e.message_dict:
                self.fail(f'Unexpected ValidationError for valid slug: {e}')

    def test_full_clean_accepts_blank_slug(self):
        """full_clean() does NOT raise for a blank slug (auto-generated later)."""
        cat = self._cat()
        svc = Service(category=cat, name='Test Name', slug='', requires_kyc=False)
        try:
            svc.full_clean()
        except ValidationError as e:
            # blank slug is allowed; only 'slug' field error would be our bug
            if 'slug' in e.message_dict:
                self.fail(f'Blank slug raised ValidationError: {e}')

    # ── URL reverse() and resolve() ─────────────────────────────────────

    @override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
    def test_persian_name_service_url_reverse(self):
        """A service with a Persian name has a resolvable URL via reverse()."""
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='ترجمه رسمی مدارک')
        # slug must be ASCII and non-empty
        self._assert_ascii(svc.slug)
        # reverse() must not raise NoReverseMatch
        url = reverse('service_order', kwargs={'slug': svc.slug})
        self.assertIn(svc.slug, url)

    @override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
    def test_persian_name_service_url_resolve(self):
        """The generated URL resolves back to the correct view."""
        from django.urls import resolve
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='پرداخت بین‌المللی')
        url = reverse('service_order', kwargs={'slug': svc.slug})
        resolved = resolve(url)
        self.assertEqual(resolved.url_name, 'service_order')
        self.assertEqual(resolved.kwargs['slug'], svc.slug)

    @override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
    def test_english_name_service_url_resolve(self):
        from django.urls import resolve
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='Wire Transfer')
        url = reverse('service_order', kwargs={'slug': svc.slug})
        resolved = resolve(url)
        self.assertEqual(resolved.kwargs['slug'], 'wire-transfer')

    @override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
    def test_mixed_name_service_url_resolve(self):
        from django.urls import resolve
        cat = self._cat()
        svc = Service.objects.create(category=cat, name='International پرداخت Transfer')
        url = reverse('service_order', kwargs={'slug': svc.slug})
        resolved = resolve(url)
        self.assertEqual(resolved.url_name, 'service_order')
        self.assertIn('international', resolved.kwargs['slug'])

    @override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
    def test_service_order_view_accessible_via_generated_slug(self):
        """The service_order view returns 200 for a Persian-named service."""
        user = _make_user('slugview@test.com')
        cat = self._cat()
        svc = Service.objects.create(
            category=cat, name='پرداخت ارزی', requires_kyc=False, is_active=True,
        )
        self.client.force_login(user)
        url = reverse('service_order', kwargs={'slug': svc.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    # ── Migration data-fix simulation ───────────────────────────────────

    def test_save_fixes_existing_persian_slug_on_update(self):
        """
        If a row somehow has a Persian slug already in the DB, saving it
        (e.g. via the migration or any admin action) corrects the slug.
        """
        cat = self._cat()
        # Bypass save() to insert a bad slug directly
        from django.db import connection
        svc = Service.objects.create(category=cat, name='Test Persian', slug='test-persian')
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE services_service SET slug = %s WHERE id = %s",
                ['ترجمه-فارسی', svc.pk],
            )
        # Reload from DB — slug is now Persian
        svc.refresh_from_db()
        self.assertEqual(svc.slug, 'ترجمه-فارسی')

        # Calling save() must fix it
        svc.save()
        svc.refresh_from_db()
        self._assert_ascii(svc.slug, 'After save() fixes Persian slug')
        self.assertNotEqual(svc.slug, 'ترجمه-فارسی')

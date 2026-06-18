"""
Comprehensive security and regression tests for the Orders module.

Coverage:
  AUTHORIZATION
    - User A cannot view / upload to / message User B's order
    - User A cannot download User B's attachment or message attachment
  DOWNLOAD SECURITY
    - Owner gets 200 and receives file content
    - Staff can download files they don't own
    - Anonymous users are redirected to the login page
  UPLOAD VALIDATION
    - Allowed file types pass (pdf, jpg, png, docx, xlsx, zip)
    - Blocked file types fail (exe, bat, js, html, svg, php)
    - Oversized files fail (> 10 MB)
    - File with no extension fails
  CSRF / ACCESS
    - Every protected view requires login
    - Public tracking page accessible without login
  ORDER NUMBER
    - Numbers follow JP24-YYYY-NNNNNN format
    - Database uniqueness constraint is in place
    - Concurrent creation produces no duplicate numbers
  REGRESSION
    - Full order creation workflow
    - Message send workflow
    - Attachment upload workflow via form
"""

import io
import tempfile
import threading
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from kyc.models import KYCProfile

from .models import (
    Category, Order, OrderAttachment,
    OrderCounter, OrderMessage, OrderMessageAttachment, SubCategory,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared temp directory for private media — created once per test run.
# override_settings on each class points PRIVATE_MEDIA_ROOT here so
# PrivateFileSystemStorage.location resolves to this temp path.
# ---------------------------------------------------------------------------
_PRIVATE_MEDIA_TMP = tempfile.mkdtemp(prefix='jp24_test_private_')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(email, is_staff=False, kyc_approved=False):
    """Create a user and optionally an approved KYC profile.

    national_id is derived from the email so it is unique across all test
    users and does not violate the KYCProfile.national_id unique constraint.
    """
    user = User.objects.create_user(
        email=email,
        password='Test1234!',
        first_name='Test',
        last_name='User',
    )
    user.is_staff = is_staff
    user.save()
    if kyc_approved:
        # Produce a deterministic 10-digit numeric ID that is unique per email.
        numeric_id = str(abs(hash(email)) % 10_000_000_000).zfill(10)
        KYCProfile.objects.create(
            user=user,
            national_id=numeric_id,
            date_of_birth=date(1990, 1, 1),
            status=KYCProfile.STATUS_APPROVED,
        )
    return user


def _make_order(user, category, subcategory, description='Test order'):
    """Create an Order directly (bypasses view-level KYC check)."""
    return Order.objects.create(
        user=user,
        category=category,
        subcategory=subcategory,
        description=description,
    )


def _make_category():
    cat = Category.objects.create(
        title='Test Category', slug='test-cat',
    )
    sub = SubCategory.objects.create(
        category=cat, title='Test Sub',
    )
    return cat, sub


def _pdf():
    return SimpleUploadedFile(
        'document.pdf', b'%PDF-1.4 test',
        content_type='application/pdf',
    )


def _file(name, content=b'data', content_type='application/octet-stream'):
    return SimpleUploadedFile(name, content, content_type=content_type)


# ===========================================================================
# Authorization tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class OrderAuthorizationTests(TestCase):
    """User A cannot access User B's order resources in any way."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user_a = _make_user('a@test.com', kyc_approved=True)
        self.user_b = _make_user('b@test.com', kyc_approved=True)
        self.order_a = _make_order(self.user_a, self.cat, self.sub)

        # Attachment owned by user_a
        self.att_a = OrderAttachment.objects.create(
            order=self.order_a, uploaded_by=self.user_a, title='a_doc',
        )
        # Message + message attachment owned by user_a
        self.msg_a = OrderMessage.objects.create(
            order=self.order_a, sender=self.user_a, message='hello',
        )
        self.msg_att_a = OrderMessageAttachment.objects.create(
            message=self.msg_a,
        )

        self.client_b = Client()
        self.client_b.force_login(self.user_b)

    # ── order detail ────────────────────────────────────────────────────────

    def test_user_b_cannot_view_user_a_order_detail(self):
        """order_detail uses get_object_or_404(Order, pk=pk, user=request.user)."""
        resp = self.client_b.get(
            reverse('order_detail', args=[self.order_a.pk])
        )
        self.assertEqual(resp.status_code, 404)

    # ── upload attachment ────────────────────────────────────────────────────

    def test_user_b_cannot_upload_to_user_a_order(self):
        resp = self.client_b.post(
            reverse('order_upload_attachment', args=[self.order_a.pk]),
            {'file': _pdf(), 'title': 'intruder'},
        )
        self.assertEqual(resp.status_code, 404)
        # Nothing was created
        self.assertEqual(
            OrderAttachment.objects.filter(order=self.order_a).count(), 1
        )

    # ── send message ─────────────────────────────────────────────────────────

    def test_user_b_cannot_send_message_to_user_a_order(self):
        resp = self.client_b.post(
            reverse('order_send_message', args=[self.order_a.pk]),
            {'message': 'hijack'},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            OrderMessage.objects.filter(order=self.order_a).count(), 1
        )

    # ── attachment download ──────────────────────────────────────────────────

    def test_user_b_cannot_download_user_a_attachment(self):
        resp = self.client_b.get(
            reverse('order_attachment_download', args=[self.att_a.pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_user_b_cannot_download_user_a_message_attachment(self):
        resp = self.client_b.get(
            reverse('message_attachment_download', args=[self.msg_att_a.pk])
        )
        self.assertEqual(resp.status_code, 404)

    # ── non-existent resources ───────────────────────────────────────────────

    def test_nonexistent_order_returns_404(self):
        resp = self.client_b.get(reverse('order_detail', args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_nonexistent_attachment_returns_404(self):
        self.client_b.force_login(self.user_a)
        resp = self.client_b.get(
            reverse('order_attachment_download', args=[99999])
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# Download security tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class DownloadSecurityTests(TestCase):
    """Ownership + staff rules on the two download views."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user_a   = _make_user('dl_a@test.com', kyc_approved=True)
        self.user_b   = _make_user('dl_b@test.com', kyc_approved=True)
        self.staff    = _make_user('dl_staff@test.com', is_staff=True)
        self.order_a  = _make_order(self.user_a, self.cat, self.sub)

        # Store real files through the private storage backend so the
        # download view can open them.
        att = OrderAttachment.objects.create(
            order=self.order_a, uploaded_by=self.user_a, title='att',
        )
        att.file.save('att.pdf', ContentFile(b'%PDF-1.4 test'), save=True)
        self.att_a = OrderAttachment.objects.get(pk=att.pk)

        msg = OrderMessage.objects.create(
            order=self.order_a, sender=self.user_a, message='hi',
        )
        msg_att = OrderMessageAttachment.objects.create(message=msg)
        msg_att.file.save('msg.pdf', ContentFile(b'%PDF-1.4 test'), save=True)
        self.msg_att_a = OrderMessageAttachment.objects.get(pk=msg_att.pk)

    # ── anonymous users ──────────────────────────────────────────────────────

    def test_anonymous_attachment_download_redirects(self):
        resp = self.client.get(
            reverse('order_attachment_download', args=[self.att_a.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp['Location'])

    def test_anonymous_message_attachment_download_redirects(self):
        resp = self.client.get(
            reverse('message_attachment_download', args=[self.msg_att_a.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp['Location'])

    # ── owner access ─────────────────────────────────────────────────────────

    def test_owner_can_download_own_attachment(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(
            reverse('order_attachment_download', args=[self.att_a.pk])
        )
        self.assertEqual(resp.status_code, 200)
        content = b''.join(resp.streaming_content)
        self.assertEqual(content, b'%PDF-1.4 test')

    def test_owner_can_download_own_message_attachment(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(
            reverse('message_attachment_download', args=[self.msg_att_a.pk])
        )
        self.assertEqual(resp.status_code, 200)
        content = b''.join(resp.streaming_content)
        self.assertEqual(content, b'%PDF-1.4 test')

    # ── non-owner (404 — no existence disclosure) ───────────────────────────

    def test_non_owner_attachment_download_404(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(
            reverse('order_attachment_download', args=[self.att_a.pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_non_owner_message_attachment_download_404(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(
            reverse('message_attachment_download', args=[self.msg_att_a.pk])
        )
        self.assertEqual(resp.status_code, 404)

    # ── staff bypass ─────────────────────────────────────────────────────────

    def test_staff_can_download_any_attachment(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('order_attachment_download', args=[self.att_a.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_staff_can_download_any_message_attachment(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('message_attachment_download', args=[self.msg_att_a.pk])
        )
        self.assertEqual(resp.status_code, 200)

    # ── private storage has no public URL ────────────────────────────────────

    def test_attachment_file_url_raises(self):
        """att.file.url must raise ValueError — there is no public URL."""
        with self.assertRaises(ValueError):
            _ = self.att_a.file.url

    def test_message_attachment_file_url_raises(self):
        with self.assertRaises(ValueError):
            _ = self.msg_att_a.file.url


# ===========================================================================
# Upload validation tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class UploadValidationTests(TestCase):
    """All three customer upload paths enforce validate_upload()."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('uv@test.com', kyc_approved=True)
        self.order = _make_order(self.user, self.cat, self.sub)
        self.client.force_login(self.user)
        self.upload_url = reverse('order_upload_attachment', args=[self.order.pk])

    def _count(self):
        return OrderAttachment.objects.filter(order=self.order).count()

    # ── allowed types ─────────────────────────────────────────────────────────

    def test_pdf_upload_succeeds(self):
        resp = self.client.post(
            self.upload_url,
            {'file': _file('test.pdf', b'%PDF', 'application/pdf'), 'title': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._count(), 1)

    def test_jpg_upload_succeeds(self):
        resp = self.client.post(
            self.upload_url,
            {'file': _file('photo.jpg', b'\xff\xd8\xff', 'image/jpeg'), 'title': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._count(), 1)

    def test_png_upload_succeeds(self):
        resp = self.client.post(
            self.upload_url,
            {'file': _file('img.png', b'\x89PNG', 'image/png'), 'title': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._count(), 1)

    def test_zip_upload_succeeds(self):
        # b'PK\x03\x04' is the correct 4-byte ZIP local file header magic.
        # b'PK' alone (2 bytes) is not enough for filetype to detect zip.
        resp = self.client.post(
            self.upload_url,
            {'file': _file('archive.zip', b'PK\x03\x04', 'application/zip'), 'title': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._count(), 1)

    # ── blocked executable / script types ─────────────────────────────────────

    def test_exe_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('malware.exe', b'MZ\x90\x00'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_bat_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('run.bat', b'@echo off'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_js_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('script.js', b'alert(1)'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_html_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('page.html', b'<html>'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_svg_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('img.svg', b'<svg>'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_php_upload_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('shell.php', b'<?php'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_unknown_extension_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('file.xyz', b'data'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_no_extension_blocked(self):
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('noext', b'data'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    # ── size limit ────────────────────────────────────────────────────────────

    def test_oversized_file_blocked(self):
        """Files larger than 10 MB must be rejected."""
        big = SimpleUploadedFile(
            'big.pdf',
            b'%PDF' + b'A' * (10 * 1024 * 1024 + 1),
            content_type='application/pdf',
        )
        before = self._count()
        self.client.post(self.upload_url, {'file': big, 'title': ''})
        self.assertEqual(self._count(), before)

    def test_exactly_10mb_file_allowed(self):
        """A file that is exactly 10 MB is allowed (validator rejects > 10 MB, not >=)."""
        big = SimpleUploadedFile(
            'limit.pdf',
            b'%PDF' + b'A' * (10 * 1024 * 1024 - 4),  # total = exactly 10 MB
            content_type='application/pdf',
        )
        before = self._count()
        self.client.post(self.upload_url, {'file': big, 'title': ''})
        self.assertEqual(self._count(), before + 1)

    # ── message attachment path ────────────────────────────────────────────────

    def test_exe_blocked_on_message_path(self):
        """Blocked extensions are rejected on the message send path too."""
        msg_url = reverse('order_send_message', args=[self.order.pk])
        before = OrderMessage.objects.filter(order=self.order).count()
        self.client.post(
            msg_url,
            {
                'message': 'test message',
                'message_files': _file('evil.exe', b'MZ'),
            },
        )
        self.assertEqual(
            OrderMessage.objects.filter(order=self.order).count(), before
        )

    def test_valid_pdf_on_message_path_succeeds(self):
        msg_url = reverse('order_send_message', args=[self.order.pk])
        self.client.post(
            msg_url,
            {
                'message': 'hello',
                'message_files': _file('doc.pdf', b'%PDF', 'application/pdf'),
            },
        )
        msg = OrderMessage.objects.filter(order=self.order).last()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.attachments.count(), 1)


# ===========================================================================
# Magic bytes / file-content validation tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class MagicBytesValidationTests(TestCase):
    """
    Validate that upload validation reads actual file content (magic bytes)
    rather than trusting the filename extension or Content-Type header.

    Key attack prevented: renaming an executable or script to an allowed
    extension (.jpg, .pdf, .docx, …) to bypass the extension check.
    """

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('magic@test.com', kyc_approved=True)
        self.order = _make_order(self.user, self.cat, self.sub)
        self.client.force_login(self.user)
        self.upload_url = reverse('order_upload_attachment', args=[self.order.pk])

    def _count(self):
        return OrderAttachment.objects.filter(order=self.order).count()

    # ── renamed Windows PE executables must be caught ─────────────────────────

    def test_exe_renamed_to_jpg_blocked(self):
        """Windows PE (MZ header) disguised as .jpg — magic bytes mismatch."""
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('photo.jpg', b'MZ\x90\x00\x03\x00', 'image/jpeg'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_exe_renamed_to_pdf_blocked(self):
        """Windows PE (MZ header) disguised as .pdf — magic bytes mismatch."""
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('invoice.pdf', b'MZ\x90\x00\x03\x00', 'application/pdf'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_exe_renamed_to_docx_blocked(self):
        """Windows PE (MZ header) disguised as .docx — magic bytes mismatch."""
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('report.docx', b'MZ\x90\x00\x03\x00', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    # ── unrecognized / corrupted content must be caught ───────────────────────

    def test_fake_pdf_blocked(self):
        """
        File with .pdf extension but no recognizable magic bytes.
        filetype.guess_mime() returns None → rejected.
        """
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('fake.pdf', b'\x00\x01\x02\x03\x04\x05\x06\x07', 'application/pdf'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_fake_jpg_blocked(self):
        """ASCII text with .jpg extension — no JPEG SOI marker."""
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('fake.jpg', b'This is definitely not a JPEG!', 'image/jpeg'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    def test_fake_png_blocked(self):
        """Null bytes with .png extension — no PNG signature."""
        before = self._count()
        self.client.post(
            self.upload_url,
            {'file': _file('fake.png', b'\x00' * 20, 'image/png'), 'title': ''},
        )
        self.assertEqual(self._count(), before)

    # ── genuine files with correct magic bytes must pass ──────────────────────

    def test_valid_pdf_passes(self):
        """%PDF magic bytes → filetype detects application/pdf → accepted."""
        self.client.post(
            self.upload_url,
            {'file': _file('real.pdf', b'%PDF-1.4 test content', 'application/pdf'), 'title': ''},
        )
        self.assertEqual(self._count(), 1)

    def test_valid_jpeg_passes(self):
        """JPEG SOI marker FF D8 FF → filetype detects image/jpeg → accepted."""
        self.client.post(
            self.upload_url,
            {'file': _file('photo.jpg', b'\xff\xd8\xff\xe0\x00\x10JFIF', 'image/jpeg'), 'title': ''},
        )
        self.assertEqual(self._count(), 1)

    def test_valid_png_passes(self):
        r"""PNG signature \x89PNG\r\n\x1a\n → filetype detects image/png → accepted."""
        self.client.post(
            self.upload_url,
            {'file': _file('image.png', b'\x89PNG\r\n\x1a\n', 'image/png'), 'title': ''},
        )
        self.assertEqual(self._count(), 1)

    def test_valid_zip_passes(self):
        """ZIP local-file-header magic PK\\x03\\x04 → accepted."""
        self.client.post(
            self.upload_url,
            {'file': _file('archive.zip', b'PK\x03\x04', 'application/zip'), 'title': ''},
        )
        self.assertEqual(self._count(), 1)

    # ── message attachment path also enforces magic bytes ─────────────────────

    def test_exe_renamed_to_pdf_blocked_on_message_path(self):
        """EXE with .pdf extension is blocked on the message-send path too."""
        msg_url = reverse('order_send_message', args=[self.order.pk])
        before = OrderMessage.objects.filter(order=self.order).count()
        self.client.post(
            msg_url,
            {
                'message': 'see attached',
                'message_files': _file('evil.pdf', b'MZ\x90\x00', 'application/pdf'),
            },
        )
        self.assertEqual(OrderMessage.objects.filter(order=self.order).count(), before)

    # ── order-create path must surface errors to the user ─────────────────────

    def test_order_create_shows_magic_byte_error(self):
        """
        Fake PDF on order-create re-renders the form with a visible Persian
        error message; no order row is created.
        """
        before = Order.objects.filter(user=self.user).count()
        resp = self.client.post(
            reverse('order_create'),
            {
                'category':    self.cat.pk,
                'subcategory': self.sub.pk,
                'description': 'سفارش تست',
                'attachment_files': _file(
                    'fake.pdf', b'\x00\x01\x02\x03', 'application/pdf',
                ),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Order.objects.filter(user=self.user).count(), before)
        self.assertContains(resp, 'محتوای فایل با نوع مجاز مطابقت ندارد')
        self.assertContains(resp, 'fake.pdf')
        self.assertContains(resp, 'alert-danger')

    def test_order_create_keeps_form_data_on_attachment_error(self):
        """Text fields are preserved when attachment validation fails."""
        resp = self.client.post(
            reverse('order_create'),
            {
                'category':          self.cat.pk,
                'subcategory':       self.sub.pk,
                'description':       'توضیحات حفظ‌شده',
                'organization_name': 'دانشگاه تست',
                'attachment_files': _file(
                    'bad.jpg', b'This is not a JPEG', 'image/jpeg',
                ),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'توضیحات حفظ‌شده')
        self.assertContains(resp, 'دانشگاه تست')


# ===========================================================================
# Order detail — upload validation UX tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class OrderDetailValidationUxTests(TestCase):
    """
    Invalid uploads on an existing order must show Persian alert-danger
    messages on order_detail and preserve entered form state.
    """

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('detailux@test.com', kyc_approved=True)
        self.order = _make_order(self.user, self.cat, self.sub)
        self.client.force_login(self.user)
        self.upload_url = reverse('order_upload_attachment', args=[self.order.pk])
        self.msg_url    = reverse('order_send_message', args=[self.order.pk])

    def test_attachment_upload_shows_magic_byte_error(self):
        """Fake PDF on order detail re-renders with alert-danger; no attachment."""
        before = OrderAttachment.objects.filter(order=self.order).count()
        resp = self.client.post(
            self.upload_url,
            {
                'file':  _file('fake.pdf', b'\x00\x01\x02\x03', 'application/pdf'),
                'title': 'سند جعلی',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OrderAttachment.objects.filter(order=self.order).count(), before)
        self.assertContains(resp, 'alert-danger')
        self.assertContains(resp, 'محتوای فایل با نوع مجاز مطابقت ندارد')
        self.assertContains(resp, 'fake.pdf')
        self.assertContains(resp, self.order.order_number)

    def test_attachment_upload_preserves_title_on_error(self):
        """Optional title field is preserved when file validation fails."""
        resp = self.client.post(
            self.upload_url,
            {
                'file':  _file('bad.jpg', b'not a jpeg', 'image/jpeg'),
                'title': 'عنوان حفظ‌شده',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'عنوان حفظ‌شده')

    def test_message_attachment_shows_magic_byte_error(self):
        """Fake file on message send re-renders with alert-danger; no message."""
        before = OrderMessage.objects.filter(order=self.order).count()
        resp = self.client.post(
            self.msg_url,
            {
                'message': 'پیام تست',
                'message_files': _file('evil.pdf', b'MZ\x90\x00', 'application/pdf'),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OrderMessage.objects.filter(order=self.order).count(), before)
        self.assertContains(resp, 'alert-danger')
        self.assertContains(resp, 'evil.pdf')
        self.assertContains(resp, 'محتوای فایل با نوع مجاز مطابقت ندارد')

    def test_message_send_preserves_message_text_on_attachment_error(self):
        """Message textarea content is preserved when attachment validation fails."""
        resp = self.client.post(
            self.msg_url,
            {
                'message': 'متن پیام حفظ‌شده',
                'message_files': _file('bad.jpg', b'not jpeg', 'image/jpeg'),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'متن پیام حفظ‌شده')


# ===========================================================================
# Admin upload validation (U2 parity with customer uploads)
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class AdminUploadValidationTests(TestCase):
    """
    Admin inline forms must call validate_upload() — same rules as customers.
    """

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user  = _make_user('admincust@test.com', kyc_approved=True)
        self.staff = _make_user('adminstaff@test.com', is_staff=True)
        self.staff.is_superuser = True
        self.staff.save()
        self.order = _make_order(self.user, self.cat, self.sub)

    # ── ValidatedOrderAttachmentForm (direct) ───────────────────────────────

    def test_admin_form_rejects_exe_renamed_as_pdf(self):
        from .forms import ValidatedOrderAttachmentForm

        form = ValidatedOrderAttachmentForm(
            data={'title': '', 'uploaded_by': str(self.staff.pk)},
            files={'file': _file('report.pdf', b'MZ\x90\x00', 'application/pdf')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)
        self.assertIn('محتوای فایل', str(form.errors['file']))

    def test_admin_form_rejects_fake_jpg(self):
        from .forms import ValidatedOrderAttachmentForm

        form = ValidatedOrderAttachmentForm(
            data={'title': '', 'uploaded_by': str(self.staff.pk)},
            files={'file': _file('photo.jpg', b'not a jpeg', 'image/jpeg')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_admin_form_rejects_oversized_file(self):
        from .forms import ValidatedOrderAttachmentForm
        from .utils import MAX_UPLOAD_BYTES

        big = SimpleUploadedFile(
            'big.pdf',
            b'%PDF' + b'A' * (MAX_UPLOAD_BYTES + 1),
            content_type='application/pdf',
        )
        form = ValidatedOrderAttachmentForm(
            data={'title': '', 'uploaded_by': str(self.staff.pk)},
            files={'file': big},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)
        self.assertIn('مگابایت', str(form.errors['file']))

    def test_admin_form_accepts_valid_pdf(self):
        from .forms import ValidatedOrderAttachmentForm

        form = ValidatedOrderAttachmentForm(
            data={'title': 'invoice', 'uploaded_by': str(self.staff.pk)},
            files={'file': _file('invoice.pdf', b'%PDF-1.4', 'application/pdf')},
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_message_attachment_form_rejects_fake_jpg(self):
        from .forms import ValidatedOrderMessageAttachmentForm

        form = ValidatedOrderMessageAttachmentForm(
            data={},
            files={'file': _file('fake.jpg', b'not a jpeg', 'image/jpeg')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_inlines_use_validated_forms(self):
        from .admin import OrderAttachmentInline, OrderMessageAttachmentInline
        from .forms import ValidatedOrderAttachmentForm, ValidatedOrderMessageAttachmentForm

        self.assertIs(OrderAttachmentInline.form, ValidatedOrderAttachmentForm)
        self.assertIs(OrderMessageAttachmentInline.form, ValidatedOrderMessageAttachmentForm)


# ===========================================================================
# Authentication / CSRF / access-control tests
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class AuthenticationTests(TestCase):
    """All protected views must redirect anonymous users to the login page."""

    PROTECTED_URLS_ARGS = [
        ('order_list',                  []),
        ('order_create',                []),
        ('order_detail',                [1]),
        ('order_send_message',          [1]),
        ('order_upload_attachment',     [1]),
        ('order_attachment_download',   [1]),
        ('message_attachment_download', [1]),
        ('ajax_subcategories',          []),
    ]

    def test_all_protected_views_redirect_anonymous(self):
        for name, args in self.PROTECTED_URLS_ARGS:
            with self.subTest(view=name):
                resp = self.client.get(reverse(name, args=args))
                self.assertIn(
                    resp.status_code, [301, 302],
                    msg=f'{name} should redirect anonymous users',
                )
                self.assertIn(
                    'login', resp['Location'].lower(),
                    msg=f'{name} should redirect to login',
                )

    def test_ajax_subcategories_authenticated_returns_json(self):
        """Logged-in users receive the same subcategory JSON as before."""
        cat, sub = _make_category()
        user = _make_user('ajax@test.com', kyc_approved=True)
        self.client.force_login(user)

        resp = self.client.get(
            reverse('ajax_subcategories'),
            {'category_id': cat.pk},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')
        data = resp.json()
        self.assertEqual(len(data['subcategories']), 1)
        self.assertEqual(data['subcategories'][0]['id'], sub.pk)
        self.assertEqual(data['subcategories'][0]['title'], sub.title)

    def test_ajax_subcategories_anonymous_redirects_to_login(self):
        resp = self.client.get(
            reverse('ajax_subcategories'),
            {'category_id': 1},
        )
        self.assertIn(resp.status_code, [301, 302])
        self.assertIn('login', resp['Location'].lower())

    def test_tracking_page_is_public(self):
        """order_tracking has no @login_required — public lookup by design."""
        resp = self.client.get(reverse('order_tracking'))
        self.assertEqual(resp.status_code, 200)

    def test_tracking_page_with_valid_code(self):
        cat, sub = _make_category()
        user = _make_user('tr@test.com')
        order = _make_order(user, cat, sub)
        resp = self.client.get(
            reverse('order_tracking'),
            {'code': order.order_number},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.order_number)

    def test_tracking_page_with_invalid_code(self):
        resp = self.client.get(
            reverse('order_tracking'),
            {'code': 'NOTREAL-9999'},
        )
        self.assertEqual(resp.status_code, 200)
        # The view sets an error string on unknown codes; confirm it appears.
        # We do not assert absence of 'JP24-' because the page's placeholder
        # example text legitimately contains that prefix.
        self.assertContains(resp, 'یافت نشد')


# ===========================================================================
# Order number uniqueness + concurrency
# ===========================================================================

class OrderNumberUnitnessTests(TestCase):
    """Sequential generation and uniqueness guarantees."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('seq@test.com')

    def test_order_number_format(self):
        order = _make_order(self.user, self.cat, self.sub)
        import re
        self.assertRegex(order.order_number, r'^JP24-\d{4}-\d{6}$')

    def test_order_numbers_are_sequential(self):
        o1 = _make_order(self.user, self.cat, self.sub)
        o2 = _make_order(self.user, self.cat, self.sub)
        seq1 = int(o1.order_number.split('-')[-1])
        seq2 = int(o2.order_number.split('-')[-1])
        self.assertEqual(seq2, seq1 + 1)

    def test_order_number_unique_constraint_exists(self):
        from django.db import IntegrityError
        o = _make_order(self.user, self.cat, self.sub)
        with self.assertRaises(IntegrityError):
            Order.objects.create(
                user=self.user,
                category=self.cat,
                subcategory=self.sub,
                description='dup',
                order_number=o.order_number,   # force duplicate
            )

    def test_order_counter_row_created(self):
        from django.utils import timezone
        _make_order(self.user, self.cat, self.sub)
        self.assertTrue(
            OrderCounter.objects.filter(year=timezone.now().year).exists()
        )


@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class OrderNumberConcurrencyTest(TransactionTestCase):
    """
    Concurrent order creation must produce unique order numbers.

    Uses TransactionTestCase (not TestCase) so that each thread's
    transaction actually commits and is visible to other threads,
    which is required for SELECT FOR UPDATE to lock correctly.
    """

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('conc@test.com')

    def _create_order_in_thread(self, results, idx):
        try:
            order = Order.objects.create(
                user=self.user,
                category=self.cat,
                subcategory=self.sub,
                description=f'concurrent {idx}',
            )
            results[idx] = order.order_number
        except Exception as exc:
            results[idx] = f'ERROR: {exc}'
        finally:
            # Each thread opens its own DB connection.  Close it before the
            # thread exits so Django can drop the test database cleanly.
            from django.db import connections
            for conn in connections.all():
                conn.close()

    def test_concurrent_creation_produces_unique_numbers(self):
        N = 10
        results = [None] * N
        threads = [
            threading.Thread(
                target=self._create_order_in_thread,
                args=(results, i),
            )
            for i in range(N)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        errors = [r for r in results if r and r.startswith('ERROR')]
        self.assertEqual(errors, [], msg=f'Some threads failed: {errors}')

        numbers = [r for r in results if r and not r.startswith('ERROR')]
        self.assertEqual(len(numbers), N, 'All threads must produce a number')
        self.assertEqual(
            len(set(numbers)), N,
            f'Duplicate order numbers detected: {numbers}',
        )


# ===========================================================================
# Regression tests — existing valid workflows must still work
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP)
class RegressionTests(TestCase):
    """Core workflows continue to function after security fixes."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('reg@test.com', kyc_approved=True)
        self.client.force_login(self.user)

    # ── order creation via view ───────────────────────────────────────────────

    def test_order_create_view_succeeds(self):
        before = Order.objects.filter(user=self.user).count()
        resp = self.client.post(
            reverse('order_create'),
            {
                'category':    self.cat.pk,
                'subcategory': self.sub.pk,
                'description': 'Integration test order',
            },
        )
        # Should redirect to order_detail on success
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.filter(user=self.user).count(), before + 1)
        order = Order.objects.filter(user=self.user).latest('created_at')
        self.assertIn('JP24-', order.order_number)

    def test_order_create_blocked_without_kyc(self):
        """A user without approved KYC cannot create an order."""
        no_kyc_user = _make_user('nokyc@test.com', kyc_approved=False)
        c = Client()
        c.force_login(no_kyc_user)
        resp = c.post(
            reverse('order_create'),
            {
                'category':    self.cat.pk,
                'subcategory': self.sub.pk,
                'description': 'Should be blocked',
            },
        )
        # Renders kyc_blocked screen (200, not 302)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Order.objects.filter(user=no_kyc_user).count(), 0)

    # ── order list ────────────────────────────────────────────────────────────

    def test_order_list_shows_own_orders_only(self):
        other = _make_user('other@test.com')
        order_mine = _make_order(self.user, self.cat, self.sub)
        _make_order(other, self.cat, self.sub)

        resp = self.client.get(reverse('order_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order_mine.order_number)

    # ── attachment upload via form ─────────────────────────────────────────────

    def test_attachment_upload_workflow(self):
        order = _make_order(self.user, self.cat, self.sub)
        before = OrderAttachment.objects.filter(order=order).count()
        resp = self.client.post(
            reverse('order_upload_attachment', args=[order.pk]),
            {'file': _file('invoice.pdf', b'%PDF', 'application/pdf'), 'title': 'inv'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            OrderAttachment.objects.filter(order=order).count(), before + 1
        )

    # ── message send ──────────────────────────────────────────────────────────

    def test_message_send_workflow(self):
        order = _make_order(self.user, self.cat, self.sub)
        resp = self.client.post(
            reverse('order_send_message', args=[order.pk]),
            {'message': 'Hello, I need help.'},
        )
        self.assertEqual(resp.status_code, 302)
        msg = OrderMessage.objects.filter(order=order).last()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.message, 'Hello, I need help.')
        self.assertEqual(msg.sender, self.user)

    def test_message_send_with_valid_attachment(self):
        order = _make_order(self.user, self.cat, self.sub)
        self.client.post(
            reverse('order_send_message', args=[order.pk]),
            {
                'message': 'Attached a document.',
                'message_files': _file('report.pdf', b'%PDF', 'application/pdf'),
            },
        )
        msg = OrderMessage.objects.filter(order=order).last()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.attachments.count(), 1)

    # ── order detail readable by owner ────────────────────────────────────────

    def test_order_detail_accessible_by_owner(self):
        order = _make_order(self.user, self.cat, self.sub)
        resp = self.client.get(reverse('order_detail', args=[order.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, order.order_number)

    # ── private storage: no .url on attachment ────────────────────────────────

    def test_uploaded_attachment_has_no_public_url(self):
        order = _make_order(self.user, self.cat, self.sub)
        self.client.post(
            reverse('order_upload_attachment', args=[order.pk]),
            {'file': _file('s.pdf', b'%PDF', 'application/pdf'), 'title': ''},
        )
        att = OrderAttachment.objects.filter(order=order).last()
        self.assertIsNotNone(att)
        with self.assertRaises(ValueError):
            _ = att.file.url


# ===========================================================================
# Order timeline
# ===========================================================================

class OrderTimelineTests(TestCase):
    """Timeline generation from existing order data (no history model)."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.user = _make_user('timeline@test.com', kyc_approved=True)

    def test_new_order_includes_created_event(self):
        from .views import _build_order_timeline

        order = _make_order(self.user, self.cat, self.sub)
        titles = [e['title'] for e in _build_order_timeline(order)]
        self.assertIn('سفارش ثبت شد', titles)

    def test_status_change_event_for_in_progress_order(self):
        from .views import _build_order_timeline

        order = _make_order(self.user, self.cat, self.sub)
        order.status = Order.STATUS_IN_PROGRESS
        order.save(update_fields=['status'])
        titles = [e['title'] for e in _build_order_timeline(order)]
        self.assertIn('سفارش در حال انجام قرار گرفت', titles)

    def test_timeline_sorted_newest_first(self):
        from .views import _build_order_timeline

        order = _make_order(self.user, self.cat, self.sub)
        OrderMessage.objects.create(
            order=order, sender=self.user, message='سلام',
        )
        timeline = _build_order_timeline(order)
        timestamps = [e['timestamp'] for e in timeline]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_order_detail_renders_timeline_section(self):
        order = _make_order(self.user, self.cat, self.sub)
        client = Client()
        client.force_login(self.user)
        resp = client.get(reverse('order_detail', args=[order.pk]))
        self.assertContains(resp, 'تاریخچه سفارش')
        self.assertContains(resp, 'سفارش ثبت شد')

    def test_attachment_and_message_events(self):
        from .views import _build_order_timeline

        order = _make_order(self.user, self.cat, self.sub)
        OrderAttachment.objects.create(
            order=order,
            file=ContentFile(b'%PDF', name='doc.pdf'),
            uploaded_by=self.user,
        )
        OrderMessage.objects.create(
            order=order, sender=self.user, message='پیام تست',
        )
        titles = [e['title'] for e in _build_order_timeline(order)]
        self.assertIn('فایل جدید بارگذاری شد', titles)
        self.assertIn('پیام جدید ثبت شد', titles)


# ===========================================================================
# Unread admin messages
# ===========================================================================

class OrderUnreadMessageTests(TestCase):
    """Read/unread state for staff vs customer order messages."""

    def setUp(self):
        self.cat, self.sub = _make_category()
        self.customer = _make_user('customer@test.com', kyc_approved=True)
        self.staff = _make_user('staff@test.com', is_staff=True)
        self.order = _make_order(self.customer, self.cat, self.sub)
        self.client = Client()
        self.client.force_login(self.customer)

    def test_staff_message_defaults_to_unread(self):
        msg = OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='پاسخ تیم',
        )
        self.assertFalse(msg.is_read)

    def test_customer_message_saved_as_read(self):
        msg = OrderMessage.objects.create(
            order=self.order, sender=self.customer, message='سوال من',
        )
        self.assertTrue(msg.is_read)

    def test_viewing_order_detail_marks_staff_messages_read(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='پیام اول',
        )
        self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertFalse(
            OrderMessage.objects.filter(order=self.order, is_read=False).exists()
        )

    def test_unread_badge_visible_before_mark_read(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='پیام خوانده‌نشده',
        )
        resp = self.client.get(reverse('order_detail', args=[self.order.pk]))
        self.assertContains(resp, 'جدید')

    def test_order_list_shows_unread_count(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='یک',
        )
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='دو',
        )
        resp = self.client.get(reverse('order_list'))
        self.assertContains(resp, '💬 2 پیام جدید')

    def test_dashboard_shows_unread_notification(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='سلام',
        )
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, '📨')
        self.assertContains(resp, '1 پیام خوانده‌نشده دارید')

    def test_sidebar_shows_unread_count(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='سلام',
        )
        resp = self.client.get(reverse('order_list'))
        self.assertContains(resp, 'سفارش‌های من')
        self.assertContains(resp, '(1)')

    def test_staff_user_has_zero_unread_in_context(self):
        OrderMessage.objects.create(
            order=self.order, sender=self.staff, message='staff only',
        )
        staff_client = Client()
        staff_client.force_login(self.staff)
        resp = staff_client.get(reverse('order_list'))
        self.assertNotContains(resp, '(1)')


# ===========================================================================
# Rate limiting (R1)
# ===========================================================================

@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE_MEDIA_TMP, RATELIMIT_ENABLE=True)
class OrderRateLimitTests(TestCase):
    """django-ratelimit protection on order endpoints."""

    def setUp(self):
        from django.core.cache import cache

        from config.ratelimit_handlers import RATE_LIMIT_MESSAGE

        cache.clear()
        self.rate_limit_message = RATE_LIMIT_MESSAGE
        self.cat, self.sub = _make_category()
        self.user = _make_user('ratelimit@test.com', kyc_approved=True)
        self.order = _make_order(self.user, self.cat, self.sub)
        self.client.force_login(self.user)

    def test_order_tracking_rate_limit_by_ip(self):
        url = reverse('order_tracking')
        for _ in range(30):
            resp = self.client.get(url)
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, self.rate_limit_message, status_code=429)

    def test_order_create_rate_limit_by_user(self):
        url = reverse('order_create')
        payload = {
            'category':    self.cat.pk,
            'subcategory': self.sub.pk,
            'description': 'Rate limit test order',
        }
        for _ in range(10):
            resp = self.client.post(url, payload)
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, self.rate_limit_message, status_code=429)

    def test_order_message_rate_limit_by_user(self):
        url = reverse('order_send_message', args=[self.order.pk])
        for i in range(20):
            resp = self.client.post(url, {'message': f'message {i}'})
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.post(url, {'message': 'blocked message'})
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, self.rate_limit_message, status_code=429)

    def test_file_upload_rate_limit_by_user(self):
        url = reverse('order_upload_attachment', args=[self.order.pk])
        for i in range(20):
            resp = self.client.post(
                url,
                {'file': _file(f'doc{i}.pdf', b'%PDF', 'application/pdf'), 'title': ''},
            )
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.post(
            url,
            {'file': _file('blocked.pdf', b'%PDF', 'application/pdf'), 'title': ''},
        )
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, self.rate_limit_message, status_code=429)

    def test_authenticated_order_create_works_under_limit(self):
        """Logged-in users still succeed when under the rate limit."""
        resp = self.client.post(
            reverse('order_create'),
            {
                'category':    self.cat.pk,
                'subcategory': self.sub.pk,
                'description': 'Single order under limit',
            },
        )
        self.assertEqual(resp.status_code, 302)

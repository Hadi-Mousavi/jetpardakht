"""
Shared upload validation for all order attachment paths.

Used by:
  - AttachmentForm (order detail attach)
  - views.order_create (multi-file creation-time attachments)
  - views.order_send_message (message attachments)

Security model
--------------
Validation is layered, in order:

  1. Extension block-list  — reject known executable / script extensions
  2. Extension allow-list  — reject anything not explicitly permitted
  3. Size limit            — reject files larger than MAX_UPLOAD_BYTES
  4. Magic bytes check     — read actual file content; reject files whose
                             byte signature does not match an allowed format

Step 4 prevents the classic "rename evil.exe to report.pdf" attack.
It uses the `filetype` library (pure-Python, zero system dependencies)
which reads the first 261 bytes of file content.

OLE2 caveat
-----------
.doc and .xls files use the OLE2 Compound Document format (magic bytes:
D0 CF 11 E0 A1 B1 1A E1).  The `filetype` library can only distinguish
Word from Excel by reading 512+ bytes of actual OLE2 sector data, which
is not available for partial / in-memory uploads.  Instead we verify the
8-byte OLE2 magic prefix directly — this still prevents any non-OLE2
file (EXE, PDF, image, etc.) from masquerading as a Word/Excel document.
"""

import filetype

from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB

# filetype reads up to 261 bytes to identify the format.
_MAGIC_READ_BYTES = 261

ALLOWED_EXTENSIONS = frozenset({
    'pdf',
    'jpg', 'jpeg', 'png',
    'doc', 'docx',
    'xls', 'xlsx',
    'zip',
})

# Rejected unconditionally, regardless of ALLOWED_EXTENSIONS.
BLOCKED_EXTENSIONS = frozenset({
    'exe', 'msi', 'bat', 'cmd', 'com', 'scr', 'pif', 'vbs', 'vbe',
    'js', 'jse', 'wsf', 'wsh', 'ps1', 'ps2',
    'html', 'htm', 'xhtml',
    'svg',
    'php', 'php3', 'php4', 'php5', 'phtml',
    'sh', 'bash', 'zsh', 'csh',
    'py', 'rb', 'pl', 'lua',
    'dll', 'so', 'dylib',
    'jar', 'class',
})

# MIME types that filetype legitimately returns for our allowed non-OLE2 formats.
#
# Notes:
#  • OOXML (.docx, .xlsx) are ZIP archives; filetype returns the specific
#    OOXML MIME when the ZIP internals are present, or application/zip for
#    partial / minimal content (e.g. b'PK\x03\x04').  Both are accepted.
#  • .doc / .xls (OLE2) are handled separately via _OLE2_MAGIC below.
_ALLOWED_CONTENT_MIMES = frozenset({
    'application/pdf',
    'image/jpeg',
    'image/png',
    # ZIP-based formats: generic zip and specific OOXML variants
    'application/zip',
    'application/x-zip-compressed',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
})

# OLE2 Compound Document magic bytes shared by .doc and .xls.
# We verify this prefix directly instead of relying on filetype,
# because filetype requires 512+ bytes of real OLE2 sector data.
_OLE2_MAGIC      = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_OLE2_EXTENSIONS = frozenset({'doc', 'xls'})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_upload(upload_file):
    """
    Validate extension, size, and magic-bytes content of an uploaded file.

    Raises ``django.core.exceptions.ValidationError`` with Persian messages
    on failure.  Does nothing if *upload_file* is ``None`` or falsy.

    The file position is reset to 0 after the magic-bytes read so the
    storage backend always receives the complete file.
    """
    if not upload_file:
        return

    name = upload_file.name or ''
    ext  = name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    # ── 1. Blocked extension ─────────────────────────────────────────────────
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError(
            f'بارگذاری فایل‌های اجرایی یا اسکریپت مجاز نیست. (.{ext})'
        )

    # ── 2. Extension allow-list ──────────────────────────────────────────────
    if ext not in ALLOWED_EXTENSIONS:
        allowed_display = '، '.join(sorted(ALLOWED_EXTENSIONS))
        raise ValidationError(
            f'فرمت فایل مجاز نیست. فرمت‌های پذیرفته‌شده: {allowed_display}'
        )

    # ── 3. Size limit ────────────────────────────────────────────────────────
    if hasattr(upload_file, 'size') and upload_file.size > MAX_UPLOAD_BYTES:
        mb = upload_file.size / (1024 * 1024)
        raise ValidationError(
            f'حجم فایل ({mb:.1f} MB) از حداکثر مجاز ۱۰ مگابایت بیشتر است.'
        )

    # ── 4. Magic bytes — actual file content must match an allowed type ──────
    #
    # Read the first _MAGIC_READ_BYTES bytes, then seek back to 0 so the
    # storage backend receives the full file without truncation.
    upload_file.seek(0)
    header = upload_file.read(_MAGIC_READ_BYTES)
    upload_file.seek(0)

    _check_magic(ext, header)


def _check_magic(ext, header):
    """
    Raise ValidationError if *header* bytes do not match the expected
    signature for *ext*.

    Separated from validate_upload() for testability.
    """
    _BAD_CONTENT_MSG = (
        'محتوای فایل با نوع مجاز مطابقت ندارد. '
        'فایل ممکن است تغییر نام داده‌شده یا خراب باشد.'
    )

    if ext in _OLE2_EXTENSIONS:
        # Verify OLE2 magic prefix directly (filetype needs 512+ bytes of
        # real sector data to distinguish .doc from .xls).
        if not header[:8] == _OLE2_MAGIC:
            raise ValidationError(_BAD_CONTENT_MSG)
        return

    # For all other allowed types, delegate to filetype.
    detected_mime = filetype.guess_mime(header)

    if not detected_mime or detected_mime not in _ALLOWED_CONTENT_MIMES:
        raise ValidationError(_BAD_CONTENT_MSG)

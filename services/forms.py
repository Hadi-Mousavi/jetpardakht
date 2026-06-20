"""
Dynamic order form engine for the services catalog.

``build_order_form(service, data, files)`` inspects the ServiceField records
attached to a Service and returns a fully-bound Django Form whose fields are
generated at runtime — no hard-coded form class needed.

Validation layers per field type
---------------------------------
text       → max 2 000 chars
textarea   → max 10 000 chars
number     → decimal / numeric
email      → RFC-5322 format check
url        → full URL (scheme required)
date       → ISO 8601 date
select     → choice must exist in choices_json
file       → reuses validate_service_upload() (jpg/jpeg/png/pdf, ≤10 MB, magic bytes)
"""

import json

from django import forms
from django.core.exceptions import ValidationError

from orders.utils import MAX_UPLOAD_BYTES

# Allowed extensions and MIME types for SERVICE file uploads (narrower than
# the generic orders allow-list which also accepts doc/xls/zip).
_SERVICE_ALLOWED_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'pdf'})
_SERVICE_ALLOWED_MIMES = frozenset({
    'image/jpeg',
    'image/png',
    'application/pdf',
})


def validate_service_upload(upload_file):
    """
    Validate a file upload for the service dynamic form.

    Allowed formats: jpg, jpeg, png, pdf — max 10 MB — magic-bytes verified.
    Raises ValidationError on failure.  Leaves file position at 0.
    """
    if not upload_file:
        return

    import filetype  # pure-Python library already in requirements

    name = upload_file.name or ''
    ext  = name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    if ext not in _SERVICE_ALLOWED_EXTENSIONS:
        raise ValidationError(
            'فرمت فایل مجاز نیست. فرمت‌های پذیرفته‌شده: jpg، jpeg، png، pdf'
        )

    if hasattr(upload_file, 'size') and upload_file.size > MAX_UPLOAD_BYTES:
        mb = upload_file.size / (1024 * 1024)
        raise ValidationError(
            f'حجم فایل ({mb:.1f} MB) از حداکثر مجاز ۱۰ مگابایت بیشتر است.'
        )

    upload_file.seek(0)
    header = upload_file.read(261)
    upload_file.seek(0)

    detected_mime = filetype.guess_mime(header)
    if not detected_mime or detected_mime not in _SERVICE_ALLOWED_MIMES:
        raise ValidationError(
            'محتوای فایل با نوع مجاز مطابقت ندارد. '
            'فایل ممکن است تغییر نام داده‌شده یا خراب باشد.'
        )


# ---------------------------------------------------------------------------
# Field factories
# ---------------------------------------------------------------------------

_WIDGET_CLASS = 'form-control'
_SELECT_CLASS = 'form-select'


def _make_field(service_field):
    """Return a Django form field for the given ServiceField, or None."""
    common = dict(
        label=service_field.label,
        required=service_field.is_required,
        help_text=service_field.help_text,
    )
    ph = service_field.placeholder
    ft = service_field.field_type

    if ft == 'text':
        return forms.CharField(
            max_length=2_000,
            widget=forms.TextInput(attrs={'class': _WIDGET_CLASS, 'placeholder': ph}),
            **common,
        )

    if ft == 'textarea':
        return forms.CharField(
            max_length=10_000,
            widget=forms.Textarea(attrs={'class': _WIDGET_CLASS, 'rows': 4, 'placeholder': ph}),
            **common,
        )

    if ft == 'number':
        return forms.DecimalField(
            widget=forms.NumberInput(attrs={'class': _WIDGET_CLASS, 'placeholder': ph}),
            **common,
        )

    if ft == 'email':
        return forms.EmailField(
            widget=forms.EmailInput(attrs={'class': _WIDGET_CLASS, 'placeholder': ph}),
            **common,
        )

    if ft == 'url':
        return forms.URLField(
            widget=forms.URLInput(attrs={'class': _WIDGET_CLASS, 'placeholder': ph}),
            **common,
        )

    if ft == 'date':
        return forms.DateField(
            widget=forms.DateInput(attrs={'class': _WIDGET_CLASS, 'type': 'date'}),
            **common,
        )

    if ft == 'select':
        choices = service_field.parsed_choices()
        return forms.ChoiceField(
            choices=[('', '— انتخاب کنید —')] + choices,
            widget=forms.Select(attrs={'class': _SELECT_CLASS}),
            **common,
        )

    if ft == 'file':
        return _ServiceFileField(service_field=service_field, **common)

    return None


class _ServiceFileField(forms.FileField):
    """FileField that enforces service-specific upload validation."""

    def __init__(self, *args, service_field=None, **kwargs):
        kwargs.setdefault('widget', forms.ClearableFileInput(attrs={
            'class': _WIDGET_CLASS,
            'accept': 'image/jpeg,image/png,application/pdf',
        }))
        super().__init__(*args, **kwargs)
        self._service_field = service_field

    def clean(self, data, initial=None):
        f = super().clean(data, initial)
        if f:
            validate_service_upload(f)
        return f


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_order_form(service, data=None, files=None):
    """
    Build and return a Django Form instance for the given Service.

    The returned class is generated dynamically from the Service's ServiceField
    records.  Pass ``data`` and ``files`` from request.POST / request.FILES to
    get a bound form suitable for validation.
    """
    field_dict = {}
    for sf in service.fields.order_by('sort_order', 'id'):
        field = _make_field(sf)
        if field is not None:
            field_dict[sf.field_name] = field

    FormClass = type('DynamicOrderForm', (forms.Form,), field_dict)
    return FormClass(data=data, files=files)

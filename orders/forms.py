from django import forms

from .models import Category, Order, OrderAttachment, OrderMessage, OrderMessageAttachment, SubCategory
from .utils import validate_upload

_INPUT   = 'form-control'
_SELECT  = 'form-select'


class OrderCreateForm(forms.ModelForm):

    class Meta:
        model  = Order
        fields = [
            'category', 'subcategory',
            'organization_name', 'amount', 'currency',
            'deadline', 'description', 'customer_note',
            # assigned_admin is intentionally excluded — admin-only field
        ]
        labels = {
            'category':          'دسته‌بندی',
            'subcategory':       'زیر دسته‌بندی',
            'organization_name': 'نام سازمان / دانشگاه',
            'amount':            'مبلغ',
            'currency':          'ارز',
            'deadline':          'ددلاین',
            'description':       'توضیحات',
            'customer_note':     'یادداشت مشتری',
        }
        widgets = {
            'category':          forms.Select(attrs={'class': _SELECT}),
            'subcategory':       forms.Select(attrs={'class': _SELECT}),
            'organization_name': forms.TextInput(attrs={
                'class': _INPUT,
                'placeholder': 'مثال: دانشگاه تورنتو',
            }),
            'amount': forms.NumberInput(attrs={
                'class': _INPUT, 'step': '0.01', 'min': '0',
                'dir': 'ltr', 'placeholder': '0.00',
            }),
            'currency': forms.TextInput(attrs={
                'class': _INPUT, 'placeholder': 'USD',
                'dir': 'ltr', 'maxlength': '10',
            }),
            'deadline': forms.DateInput(attrs={
                'class': _INPUT, 'type': 'date', 'dir': 'ltr',
            }),
            'description': forms.Textarea(attrs={
                'class': _INPUT, 'rows': 5,
                'placeholder': 'جزئیات درخواست خود را شرح دهید…',
            }),
            'customer_note': forms.Textarea(attrs={
                'class': _INPUT, 'rows': 3,
                'placeholder': 'یادداشت یا نکته اضافی برای تیم جت‌پی‌۲۴ (اختیاری)',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional fields
        for f in ('organization_name', 'amount', 'currency', 'deadline', 'customer_note'):
            self.fields[f].required = False

        # Active categories only
        self.fields['category'].queryset    = Category.objects.filter(is_active=True)
        self.fields['category'].empty_label = '— انتخاب دسته‌بندی —'

        # Subcategories populated via AJAX on the frontend; pre-populate on
        # re-render after POST error or when editing an existing instance.
        self.fields['subcategory'].empty_label = '— ابتدا دسته‌بندی را انتخاب کنید —'

        if 'category' in self.data:
            try:
                cat_id = int(self.data['category'])
                self.fields['subcategory'].queryset = SubCategory.objects.filter(
                    category_id=cat_id, is_active=True,
                )
            except (ValueError, TypeError):
                self.fields['subcategory'].queryset = SubCategory.objects.none()
        elif self.instance.pk and self.instance.category_id:
            self.fields['subcategory'].queryset = SubCategory.objects.filter(
                category=self.instance.category, is_active=True,
            )
        else:
            self.fields['subcategory'].queryset = SubCategory.objects.none()


class MessageForm(forms.ModelForm):
    class Meta:
        model  = OrderMessage
        fields = ['message']
        labels = {'message': ''}
        widgets = {
            'message': forms.Textarea(attrs={
                'class': _INPUT, 'rows': 3,
                'placeholder': 'پیام خود را بنویسید…',
            }),
        }


class AttachmentForm(forms.ModelForm):
    class Meta:
        model  = OrderAttachment
        fields = ['file', 'title']
        labels = {'file': 'انتخاب فایل', 'title': 'عنوان فایل'}
        widgets = {
            'file': forms.FileInput(attrs={
                'class': _INPUT,
                'accept': 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.zip',
            }),
            'title': forms.TextInput(attrs={
                'class': _INPUT, 'placeholder': 'عنوان فایل (اختیاری)',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = False

    def clean_file(self):
        f = self.cleaned_data.get('file')
        validate_upload(f)
        return f


class ValidatedOrderAttachmentForm(forms.ModelForm):
    """
    Admin inline form for OrderAttachment.

    Uses the same validate_upload() pipeline as customer AttachmentForm.
    """

    class Meta:
        model  = OrderAttachment
        fields = ['file', 'title', 'uploaded_by']

    def clean_file(self):
        f = self.cleaned_data.get('file')
        validate_upload(f)
        return f


class ValidatedOrderMessageAttachmentForm(forms.ModelForm):
    """
    Admin inline form for OrderMessageAttachment.

    Uses the same validate_upload() pipeline as customer message uploads.
    """

    class Meta:
        model  = OrderMessageAttachment
        fields = ['file']

    def clean_file(self):
        f = self.cleaned_data.get('file')
        validate_upload(f)
        return f

from pathlib import Path

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .captcha import issue_captcha, verify_captcha
from .models import AuctionSettlement, Bid, ModelAsset, NFTAsset, User


def _captcha_field() -> forms.CharField:
    return forms.CharField(
        label="Kode CAPTCHA",
        max_length=8,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "Masukkan kode pada gambar",
            }
        ),
        error_messages={
            "required": "Kode CAPTCHA wajib diisi.",
        },
    )


class _CaptchaValidationMixin:
    request = None

    def _prepare_captcha(self, request):
        self.request = request
        if request is not None:
            issue_captcha(request)

    def clean_captcha(self):
        value = self.cleaned_data.get("captcha", "")
        if self.request is None or not verify_captcha(self.request, value):
            if self.request is not None:
                issue_captcha(self.request, force=True)
            raise forms.ValidationError(
                "Kode CAPTCHA salah atau sudah kedaluwarsa. Masukkan kode yang baru."
            )
        return value


class RegistrationForm(_CaptchaValidationMixin, UserCreationForm):
    email = forms.EmailField(required=True)
    captcha = _captcha_field()

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._prepare_captcha(request)
        self.order_fields(
            (
                "username",
                "email",
                "display_name",
                "role",
                "password1",
                "password2",
                "captcha",
            )
        )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "display_name",
            "role",
            "password1",
            "password2",
            "captcha",
        )


class CaptchaAuthenticationForm(_CaptchaValidationMixin, AuthenticationForm):
    captcha = _captcha_field()

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self._prepare_captcha(request)
        self.order_fields(("username", "password", "captcha"))


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "display_name",
            "email",
            "bio",
            "wallet_address",
            "avatar",
        )
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}


class NFTForm(forms.ModelForm):
    class Meta:
        model = NFTAsset
        fields = (
            "title",
            "description",
            "image",
            "image_url",
            "starting_price",
            "reserve_price",
            "auction_starts_at",
            "auction_ends_at",
            "metadata",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "auction_starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "auction_ends_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "metadata": forms.Textarea(attrs={"rows": 5}),
        }


class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = ("amount",)
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"})
        }


class AuctionInvoiceForm(forms.Form):
    payment_method = forms.ChoiceField(
        label="Metode pembayaran",
        choices=AuctionSettlement.PaymentMethod.choices,
    )
    payment_due_hours = forms.IntegerField(
        label="Batas pembayaran",
        min_value=1,
        max_value=168,
        initial=48,
        help_text="Jumlah jam sejak invoice dikirim. Maksimal 7 hari.",
    )
    payment_instructions = forms.CharField(
        label="Instruksi pembayaran",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": (
                    "Contoh: Transfer ke rekening ..., atas nama ..., "
                    "lalu unggah bukti pembayaran pada halaman invoice."
                ),
            }
        ),
    )


class PaymentSubmissionForm(forms.ModelForm):
    class Meta:
        model = AuctionSettlement
        fields = (
            "payment_reference",
            "payment_proof",
            "buyer_note",
        )
        labels = {
            "payment_reference": "Nomor referensi pembayaran",
            "payment_proof": "Bukti pembayaran",
            "buyer_note": "Catatan untuk creator",
        }
        widgets = {
            "buyer_note": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_payment_proof(self):
        value = self.cleaned_data.get("payment_proof")
        if value is None:
            return value
        suffix = Path(value.name).suffix.casefold()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
            raise forms.ValidationError(
                "Bukti pembayaran harus berupa JPG, PNG, WEBP, atau PDF."
            )
        if value.size > 10 * 1024 * 1024:
            raise forms.ValidationError(
                "Ukuran bukti pembayaran maksimal 10 MB."
            )
        return value

    def clean(self):
        cleaned = super().clean()
        reference = str(cleaned.get("payment_reference") or "").strip()
        proof = cleaned.get("payment_proof")
        existing_proof = getattr(self.instance, "payment_proof", None)
        if not reference and not proof and not existing_proof:
            raise forms.ValidationError(
                "Isi nomor referensi atau unggah bukti pembayaran."
            )
        return cleaned


class ModelAssetForm(forms.ModelForm):
    class Meta:
        model = ModelAsset
        fields = (
            "name",
            "description",
            "category",
            "version",
            "base_model_family",
            "trigger_words",
            "capabilities",
            "model_file",
            "preview",
            "preview_url",
            "price",
            "license_type",
            "commercial_use",
            "metadata",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "trigger_words": forms.Textarea(attrs={"rows": 3}),
            "capabilities": forms.Textarea(attrs={"rows": 3}),
            "metadata": forms.Textarea(attrs={"rows": 4}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def clean_model_file(self):
        value = self.cleaned_data.get("model_file")
        if value is None:
            return value
        if not Path(value.name).suffix.casefold() == ".batikmodel":
            raise forms.ValidationError(
                "File model harus memakai ekstensi .batikmodel."
            )
        return value

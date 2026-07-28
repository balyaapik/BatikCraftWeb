from pathlib import Path

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from .captcha import issue_captcha, verify_captcha
from .models import (
    AuctionSettlement,
    Bid,
    MarketplaceSetting,
    ModelAsset,
    NFTAsset,
    User,
    available_timezones_sorted,
)


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
                issue_captcha(request=self.request, force=True)
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
    timezone_name = forms.ChoiceField(
        required=False,
        label="Zona waktu",
        help_text="Kosongkan untuk mengikuti zona waktu default marketplace.",
    )

    class Meta:
        model = User
        fields = (
            "display_name",
            "email",
            "bio",
            "wallet_address",
            "avatar",
            "timezone_name",
            "payout_bank_code",
            "payout_account_number",
            "payout_account_holder",
        )
        labels = {
            "payout_bank_code": "Kode bank payout",
            "payout_account_number": "Nomor rekening payout",
            "payout_account_holder": "Nama pemilik rekening",
        }
        help_texts = {
            "payout_bank_code": (
                "Kode channel payout Xendit, misalnya BCA atau ID_BCA. "
                "Ketiga data rekening harus diisi lengkap."
            ),
        }
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        default = MarketplaceSetting.load().default_timezone
        self.fields["timezone_name"].choices = [
            ("", f"Ikuti default marketplace ({default})"),
            *((name, name) for name in available_timezones_sorted()),
        ]
        if getattr(self.instance, "role", None) != User.Role.CREATOR:
            for name in (
                "payout_bank_code",
                "payout_account_number",
                "payout_account_holder",
            ):
                self.fields.pop(name, None)

    def clean(self):
        cleaned = super().clean()
        payout_fields = (
            "payout_bank_code",
            "payout_account_number",
            "payout_account_holder",
        )
        present = [str(cleaned.get(name) or "").strip() for name in payout_fields]
        if any(present) and not all(present):
            raise forms.ValidationError(
                "Kode bank, nomor rekening, dan nama pemilik rekening harus diisi lengkap."
            )
        return cleaned


class NFTForm(forms.ModelForm):
    """Form web untuk menyunting metadata NFT dari paket BatikCraft Studio."""

    class Meta:
        model = NFTAsset
        fields = (
            "title",
            "description",
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

    def clean(self):
        cleaned = super().clean()
        starts = cleaned.get("auction_starts_at") or timezone.now()
        ends = cleaned.get("auction_ends_at")
        starting_price = cleaned.get("starting_price")
        reserve_price = cleaned.get("reserve_price")
        if ends is None:
            self.add_error(
                "auction_ends_at",
                "Batas akhir lelang wajib diisi agar pemenang dapat ditagih.",
            )
        elif ends <= starts:
            self.add_error(
                "auction_ends_at",
                "Waktu selesai harus setelah waktu mulai lelang.",
            )
        if (
            reserve_price is not None
            and starting_price is not None
            and reserve_price < starting_price
        ):
            self.add_error(
                "reserve_price",
                "Reserve price tidak boleh lebih rendah dari harga awal.",
            )
        return cleaned


class AuctionRelistForm(forms.Form):
    auction_ends_at = forms.DateTimeField(
        label="Batas akhir lelang baru",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    reserve_price = forms.DecimalField(
        label="Reserve price",
        required=False,
        min_value=0,
        max_digits=18,
        decimal_places=2,
    )

    def clean_auction_ends_at(self):
        value = self.cleaned_data["auction_ends_at"]
        if value <= timezone.now():
            raise forms.ValidationError("Batas akhir baru harus berada di masa depan.")
        return value


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

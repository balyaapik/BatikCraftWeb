from django import forms

from .models import PaymentGatewaySetting


class PaymentGatewaySettingForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        label="Xendit API key",
        widget=forms.PasswordInput(render_value=False),
        help_text="Kosongkan untuk mempertahankan API key yang sudah tersimpan.",
    )
    webhook_token = forms.CharField(
        required=False,
        label="Webhook verification token",
        widget=forms.PasswordInput(render_value=False),
        help_text=(
            "Salin verification token dari Xendit Dashboard. Kosongkan untuk "
            "mempertahankan token yang sudah tersimpan."
        ),
    )

    class Meta:
        model = PaymentGatewaySetting
        fields = (
            "enabled",
            "is_production",
            "api_key",
            "webhook_token",
            "http_timeout",
        )
        labels = {
            "enabled": "Aktifkan checkout Xendit",
            "is_production": "Gunakan mode production",
            "http_timeout": "Batas waktu koneksi (detik)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored_api_key = str(getattr(self.instance, "api_key", "") or "")
        self._stored_webhook_token = str(
            getattr(self.instance, "webhook_token", "") or ""
        )
        if self._stored_api_key:
            self.fields["api_key"].widget.attrs["placeholder"] = "API key sudah tersimpan"
        if self._stored_webhook_token:
            self.fields["webhook_token"].widget.attrs["placeholder"] = (
                "Webhook token sudah tersimpan"
            )

    def clean_api_key(self):
        return self.cleaned_data["api_key"].strip()

    def clean_webhook_token(self):
        return self.cleaned_data["webhook_token"].strip()

    def clean(self):
        cleaned = super().clean()
        enabled = bool(cleaned.get("enabled"))
        is_production = bool(cleaned.get("is_production"))
        api_key = cleaned.get("api_key") or self._stored_api_key
        webhook_token = cleaned.get("webhook_token") or self._stored_webhook_token

        if enabled and not api_key:
            self.add_error("api_key", "API key wajib diisi saat checkout diaktifkan.")
        if enabled and not webhook_token:
            self.add_error(
                "webhook_token",
                "Webhook verification token wajib diisi agar pembayaran dapat diselesaikan.",
            )

        if api_key.startswith("xnd_development_") and is_production:
            self.add_error(
                "is_production",
                "API key development tidak boleh digunakan dalam mode production.",
            )
        if api_key.startswith("xnd_production_") and not is_production:
            self.add_error(
                "is_production",
                "Aktifkan mode production untuk API key production.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.provider = PaymentGatewaySetting.Provider.XENDIT
        instance.api_key = self.cleaned_data.get("api_key") or self._stored_api_key
        instance.webhook_token = (
            self.cleaned_data.get("webhook_token") or self._stored_webhook_token
        )
        if commit:
            instance.save()
        return instance

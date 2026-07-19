from django import forms

from .models import StorageConfiguration


class StorageConfigurationForm(forms.ModelForm):
    secret_access_key = forms.CharField(
        required=False,
        label="Secret Access Key",
        widget=forms.PasswordInput(render_value=False),
        help_text="Kosongkan untuk mempertahankan secret yang sudah tersimpan.",
    )

    class Meta:
        model = StorageConfiguration
        fields = (
            "enabled",
            "account_id",
            "endpoint_override",
            "access_key_id",
            "secret_access_key",
            "bucket_name",
            "location_prefix",
            "use_signed_urls",
            "signed_url_expiry",
            "custom_domain",
        )
        widgets = {
            "account_id": forms.TextInput(attrs={"autocomplete": "off"}),
            "access_key_id": forms.TextInput(attrs={"autocomplete": "off"}),
            "endpoint_override": forms.URLInput(
                attrs={"placeholder": "https://ACCOUNT_ID.r2.cloudflarestorage.com"}
            ),
            "custom_domain": forms.TextInput(attrs={"placeholder": "assets.example.com"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.has_secret_access_key:
            self.fields["secret_access_key"].widget.attrs["placeholder"] = (
                "Secret sudah tersimpan"
            )

    def clean_account_id(self):
        return self.cleaned_data["account_id"].strip()

    def clean_access_key_id(self):
        return self.cleaned_data["access_key_id"].strip()

    def clean_secret_access_key(self):
        return self.cleaned_data["secret_access_key"].strip()

    def clean_bucket_name(self):
        return self.cleaned_data["bucket_name"].strip()

    def clean_location_prefix(self):
        return self.cleaned_data["location_prefix"].strip("/")

    def clean_endpoint_override(self):
        return self.cleaned_data["endpoint_override"].strip().rstrip("/")

    def clean_custom_domain(self):
        value = self.cleaned_data["custom_domain"].strip()
        return value.removeprefix("https://").removeprefix("http://").rstrip("/")

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        use_signed_urls = cleaned.get("use_signed_urls")
        secret = cleaned.get("secret_access_key")
        has_stored_secret = bool(self.instance and self.instance.has_secret_access_key)

        if enabled:
            required = {
                "account_id": "Account ID wajib diisi saat R2 diaktifkan.",
                "access_key_id": "Access Key ID wajib diisi saat R2 diaktifkan.",
                "bucket_name": "Nama bucket wajib diisi saat R2 diaktifkan.",
            }
            for field_name, message in required.items():
                if not cleaned.get(field_name):
                    self.add_error(field_name, message)
            if not secret and not has_stored_secret:
                self.add_error(
                    "secret_access_key",
                    "Secret Access Key wajib diisi saat R2 diaktifkan.",
                )

        if use_signed_urls and cleaned.get("custom_domain"):
            self.add_error(
                "custom_domain",
                "Custom domain tidak dapat dipakai bersama signed URL R2.",
            )
        if enabled and not use_signed_urls and not cleaned.get("custom_domain"):
            self.add_error(
                "custom_domain",
                "Custom domain publik wajib diisi jika signed URL dimatikan.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        secret = self.cleaned_data.get("secret_access_key")
        if secret:
            instance.set_secret_access_key(secret)
        if commit:
            instance.save()
        return instance

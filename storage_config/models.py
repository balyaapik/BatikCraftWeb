from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .crypto import decrypt_secret, encrypt_secret


class StorageConfiguration(models.Model):
    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=1,
        editable=False,
    )
    enabled = models.BooleanField(
        default=False,
        verbose_name="Gunakan Cloudflare R2",
    )
    account_id = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Cloudflare Account ID",
    )
    endpoint_override = models.URLField(
        blank=True,
        verbose_name="Endpoint khusus",
        help_text="Kosongkan untuk memakai endpoint R2 standar dari Account ID.",
    )
    access_key_id = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="Access Key ID",
    )
    secret_access_key_ciphertext = models.TextField(blank=True, editable=False)
    bucket_name = models.CharField(
        max_length=63,
        blank=True,
        verbose_name="Nama bucket",
    )
    location_prefix = models.CharField(
        max_length=160,
        default="media",
        blank=True,
        verbose_name="Prefix folder",
        help_text="Contoh: media. Kosongkan untuk menyimpan dari root bucket.",
    )
    use_signed_urls = models.BooleanField(
        default=True,
        verbose_name="Gunakan URL bertanda tangan",
        help_text="Direkomendasikan agar file model dan paket sumber tetap privat.",
    )
    signed_url_expiry = models.PositiveIntegerField(
        default=900,
        verbose_name="Masa berlaku URL (detik)",
    )
    custom_domain = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Custom domain publik",
        help_text="Tanpa https:// dan hanya dipakai jika URL bertanda tangan dimatikan.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="storage_configuration_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Konfigurasi penyimpanan"
        verbose_name_plural = "Konfigurasi penyimpanan"

    def __str__(self):
        return "Cloudflare R2" if self.enabled else "Penyimpanan lokal VPS"

    @classmethod
    def get_solo(cls):
        instance, _created = cls.objects.get_or_create(singleton_id=1)
        return instance

    @property
    def endpoint_url(self) -> str:
        if self.endpoint_override:
            return self.endpoint_override.rstrip("/")
        if not self.account_id:
            return ""
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @property
    def has_secret_access_key(self) -> bool:
        return bool(self.secret_access_key_ciphertext)

    @property
    def is_complete(self) -> bool:
        return bool(
            self.account_id
            and self.access_key_id
            and self.has_secret_access_key
            and self.bucket_name
            and self.endpoint_url
        )

    def set_secret_access_key(self, value: str) -> None:
        self.secret_access_key_ciphertext = encrypt_secret(value.strip())

    def get_secret_access_key(self) -> str:
        return decrypt_secret(self.secret_access_key_ciphertext)

    def clean(self):
        errors = {}
        if self.enabled:
            if not self.account_id:
                errors["account_id"] = "Account ID wajib diisi saat R2 diaktifkan."
            if not self.access_key_id:
                errors["access_key_id"] = "Access Key ID wajib diisi saat R2 diaktifkan."
            if not self.has_secret_access_key:
                errors["secret_access_key_ciphertext"] = (
                    "Secret Access Key wajib disimpan saat R2 diaktifkan."
                )
            if not self.bucket_name:
                errors["bucket_name"] = "Nama bucket wajib diisi saat R2 diaktifkan."
        if self.use_signed_urls and self.custom_domain:
            errors["custom_domain"] = (
                "Custom domain tidak dapat dipakai bersama URL bertanda tangan R2."
            )
        if not self.use_signed_urls and self.enabled and not self.custom_domain:
            errors["custom_domain"] = (
                "Isi custom domain publik ketika URL bertanda tangan dimatikan."
            )
        if self.signed_url_expiry < 60 or self.signed_url_expiry > 86400:
            errors["signed_url_expiry"] = "Gunakan nilai antara 60 dan 86400 detik."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        self.location_prefix = self.location_prefix.strip("/")
        self.custom_domain = self.custom_domain.strip().removeprefix("https://").removeprefix(
            "http://"
        ).rstrip("/")
        self.endpoint_override = self.endpoint_override.rstrip("/")
        super().save(*args, **kwargs)

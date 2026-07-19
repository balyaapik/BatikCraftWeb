import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StorageConfiguration",
            fields=[
                (
                    "singleton_id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=False,
                        verbose_name="Gunakan Cloudflare R2",
                    ),
                ),
                (
                    "account_id",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        verbose_name="Cloudflare Account ID",
                    ),
                ),
                (
                    "endpoint_override",
                    models.URLField(
                        blank=True,
                        help_text="Kosongkan untuk memakai endpoint R2 standar dari Account ID.",
                        verbose_name="Endpoint khusus",
                    ),
                ),
                (
                    "access_key_id",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="Access Key ID",
                    ),
                ),
                (
                    "secret_access_key_ciphertext",
                    models.TextField(blank=True, editable=False),
                ),
                (
                    "bucket_name",
                    models.CharField(
                        blank=True,
                        max_length=63,
                        verbose_name="Nama bucket",
                    ),
                ),
                (
                    "location_prefix",
                    models.CharField(
                        blank=True,
                        default="media",
                        help_text="Contoh: media. Kosongkan untuk menyimpan dari root bucket.",
                        max_length=160,
                        verbose_name="Prefix folder",
                    ),
                ),
                (
                    "use_signed_urls",
                    models.BooleanField(
                        default=True,
                        help_text="Direkomendasikan agar file model dan paket sumber tetap privat.",
                        verbose_name="Gunakan URL bertanda tangan",
                    ),
                ),
                (
                    "signed_url_expiry",
                    models.PositiveIntegerField(
                        default=900,
                        verbose_name="Masa berlaku URL (detik)",
                    ),
                ),
                (
                    "custom_domain",
                    models.CharField(
                        blank=True,
                        help_text="Tanpa https:// dan hanya dipakai jika URL bertanda tangan dimatikan.",
                        max_length=255,
                        verbose_name="Custom domain publik",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="storage_configuration_updates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Konfigurasi penyimpanan",
                "verbose_name_plural": "Konfigurasi penyimpanan",
            },
        ),
    ]

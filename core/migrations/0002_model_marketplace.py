# Generated manually for BatikCraft model marketplace.

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModelAsset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                (
                    "category",
                    models.CharField(default="ornament", max_length=80),
                ),
                (
                    "source_model_id",
                    models.CharField(blank=True, db_index=True, max_length=160),
                ),
                (
                    "source_app_version",
                    models.CharField(blank=True, max_length=32),
                ),
                ("version", models.CharField(default="1.0.0", max_length=40)),
                (
                    "base_model_family",
                    models.CharField(default="sdxl", max_length=80),
                ),
                ("trigger_words", models.JSONField(blank=True, default=list)),
                ("capabilities", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("model_file", models.FileField(upload_to="models/%Y/%m/")),
                (
                    "preview",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="model-previews/%Y/%m/",
                    ),
                ),
                ("preview_url", models.URLField(blank=True)),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=18,
                    ),
                ),
                (
                    "license_type",
                    models.CharField(
                        choices=[
                            ("personal", "Personal"),
                            ("commercial", "Commercial"),
                            ("extended", "Extended Commercial"),
                        ],
                        default="personal",
                        max_length=24,
                    ),
                ),
                ("commercial_use", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("listed", "Listed"),
                            ("archived", "Archived"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="model_listings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ModelPurchase",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amount_paid",
                    models.DecimalField(decimal_places=2, max_digits=18),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("paid", "Paid"),
                            ("refunded", "Refunded"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="paid",
                        max_length=16,
                    ),
                ),
                (
                    "license_snapshot",
                    models.JSONField(blank=True, default=dict),
                ),
                ("download_count", models.PositiveIntegerField(default=0)),
                ("purchased_at", models.DateTimeField(auto_now_add=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="model_purchases",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "model",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchases",
                        to="core.modelasset",
                    ),
                ),
            ],
            options={"ordering": ["-purchased_at"]},
        ),
        migrations.AddConstraint(
            model_name="modelasset",
            constraint=models.UniqueConstraint(
                condition=~models.Q(source_model_id=""),
                fields=("seller", "source_model_id", "version"),
                name="unique_seller_model_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="modelpurchase",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="paid"),
                fields=("model", "buyer"),
                name="unique_paid_model_purchase",
            ),
        ),
    ]

# Generated manually for the BatikCraft auction settlement workflow.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_mysql_partial_unique_guards"),
    ]

    operations = [
        migrations.AddField(
            model_name="nftasset",
            name="current_owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Buyer yang menerima NFT setelah pembayaran dan mint selesai.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="owned_nfts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="nftasset",
            name="minted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="nftasset",
            name="owner",
            field=models.ForeignKey(
                help_text="Creator asli NFT. Kepemilikan buyer disimpan di current_owner.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="nfts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="nftasset",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("listed", "Listed"),
                    ("awaiting_payment", "Awaiting payment"),
                    ("sold", "Sold"),
                    ("archived", "Archived"),
                ],
                db_index=True,
                default="draft",
                max_length=24,
            ),
        ),
        migrations.CreateModel(
            name="AuctionSettlement",
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
                    "public_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "invoice_number",
                    models.CharField(blank=True, max_length=40, unique=True),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("invoiced", "Menunggu persetujuan buyer"),
                            ("accepted", "Menunggu pembayaran"),
                            ("payment_submitted", "Pembayaran diajukan"),
                            ("minted", "Lunas dan NFT diterbitkan"),
                            ("declined", "Ditolak buyer"),
                            ("expired", "Kedaluwarsa"),
                            ("cancelled", "Dibatalkan"),
                        ],
                        db_index=True,
                        default="invoiced",
                        max_length=24,
                    ),
                ),
                (
                    "payment_method",
                    models.CharField(
                        choices=[
                            ("bank_transfer", "Transfer bank"),
                            ("e_wallet", "Dompet digital"),
                            ("other", "Metode lain"),
                        ],
                        default="bank_transfer",
                        max_length=24,
                    ),
                ),
                ("payment_instructions", models.TextField()),
                ("payment_due_at", models.DateTimeField(db_index=True)),
                ("payment_reference", models.CharField(blank=True, max_length=160)),
                (
                    "payment_proof",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to="payment-proofs/%Y/%m/",
                    ),
                ),
                ("buyer_note", models.TextField(blank=True)),
                ("review_note", models.TextField(blank=True)),
                (
                    "mint_reference",
                    models.CharField(
                        blank=True,
                        max_length=80,
                        null=True,
                        unique=True,
                    ),
                ),
                ("minted_to_wallet", models.CharField(blank=True, max_length=128)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("payment_submitted_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("minted_at", models.DateTimeField(blank=True, null=True)),
                ("declined_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="auction_purchases",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="auction_sales",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "nft",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="settlement",
                        to="core.nftasset",
                    ),
                ),
                (
                    "winning_bid",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="settlement",
                        to="core.bid",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0004_auction_settlement"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentGatewayAttempt",
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
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[("midtrans", "Midtrans")],
                        default="midtrans",
                        max_length=24,
                    ),
                ),
                (
                    "environment",
                    models.CharField(
                        choices=[
                            ("sandbox", "Sandbox"),
                            ("production", "Production"),
                        ],
                        default="sandbox",
                        max_length=16,
                    ),
                ),
                ("order_id", models.CharField(max_length=50, unique=True)),
                (
                    "amount",
                    models.DecimalField(decimal_places=2, max_digits=18),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Checkout dibuat"),
                            ("pending", "Menunggu pembayaran"),
                            ("paid", "Lunas"),
                            ("failed", "Gagal"),
                            ("expired", "Kedaluwarsa"),
                            ("cancelled", "Dibatalkan"),
                            ("refunded", "Dikembalikan"),
                        ],
                        db_index=True,
                        default="created",
                        max_length=20,
                    ),
                ),
                ("snap_token", models.CharField(blank=True, max_length=160)),
                ("redirect_url", models.URLField(blank=True, max_length=600)),
                (
                    "transaction_id",
                    models.CharField(blank=True, db_index=True, max_length=120),
                ),
                ("payment_type", models.CharField(blank=True, max_length=64)),
                ("fraud_status", models.CharField(blank=True, max_length=32)),
                ("gateway_status", models.CharField(blank=True, max_length=32)),
                ("gateway_response", models.JSONField(blank=True, default=dict)),
                (
                    "expires_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "settlement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="gateway_attempts",
                        to="core.auctionsettlement",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PaymentGatewayEvent",
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
                ("event_key", models.CharField(max_length=64, unique=True)),
                (
                    "transaction_status",
                    models.CharField(blank=True, max_length=32),
                ),
                ("payload", models.JSONField(default=dict)),
                ("signature_valid", models.BooleanField(default=False)),
                ("verified_with_api", models.BooleanField(default=False)),
                ("processed", models.BooleanField(default=False)),
                ("outcome", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "attempt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="payments.paymentgatewayattempt",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="paymentgatewayattempt",
            index=models.Index(
                fields=["settlement", "status"],
                name="payments_pa_settlem_721d18_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="paymentgatewayattempt",
            index=models.Index(
                fields=["provider", "order_id"],
                name="payments_pa_provide_c67606_idx",
            ),
        ),
    ]

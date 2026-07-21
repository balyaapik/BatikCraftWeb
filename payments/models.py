from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuctionSettlement


class PaymentGatewayAttempt(models.Model):
    class Provider(models.TextChoices):
        MIDTRANS = "midtrans", "Midtrans"

    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    class Status(models.TextChoices):
        CREATED = "created", "Checkout dibuat"
        PENDING = "pending", "Menunggu pembayaran"
        PAID = "paid", "Lunas"
        FAILED = "failed", "Gagal"
        EXPIRED = "expired", "Kedaluwarsa"
        CANCELLED = "cancelled", "Dibatalkan"
        REFUNDED = "refunded", "Dikembalikan"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    settlement = models.ForeignKey(
        AuctionSettlement,
        on_delete=models.PROTECT,
        related_name="gateway_attempts",
    )
    provider = models.CharField(
        max_length=24,
        choices=Provider.choices,
        default=Provider.MIDTRANS,
    )
    environment = models.CharField(
        max_length=16,
        choices=Environment.choices,
        default=Environment.SANDBOX,
    )
    order_id = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )
    snap_token = models.CharField(max_length=160, blank=True)
    redirect_url = models.URLField(max_length=600, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True, db_index=True)
    payment_type = models.CharField(max_length=64, blank=True)
    fraud_status = models.CharField(max_length=32, blank=True)
    gateway_status = models.CharField(max_length=32, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["settlement", "status"]),
            models.Index(fields=["provider", "order_id"]),
        ]

    def __str__(self):
        return f"{self.order_id} — {self.get_status_display()}"

    @property
    def is_active(self):
        if self.status not in {self.Status.CREATED, self.Status.PENDING}:
            return False
        return not self.expires_at or timezone.now() < self.expires_at

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= Decimal("0.00"):
            errors["amount"] = "Nilai pembayaran harus lebih dari nol."
        if self.settlement_id and self.amount != self.settlement.amount:
            errors["amount"] = "Nilai gateway harus sama dengan invoice lelang."
        if errors:
            raise ValidationError(errors)


class PaymentGatewayEvent(models.Model):
    attempt = models.ForeignKey(
        PaymentGatewayAttempt,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_key = models.CharField(max_length=64, unique=True)
    transaction_status = models.CharField(max_length=32, blank=True)
    payload = models.JSONField(default=dict)
    signature_valid = models.BooleanField(default=False)
    verified_with_api = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    outcome = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.attempt.order_id} — {self.transaction_status or 'event'}"

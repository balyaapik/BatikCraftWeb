import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuctionSettlement, NFTAsset, User, quantize_money


class PaymentGatewayAttempt(models.Model):
    class Provider(models.TextChoices):
        XENDIT = "xendit", "Xendit"

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

    class Purpose(models.TextChoices):
        AUCTION_SETTLEMENT = "auction_settlement", "Pelunasan invoice buyer"
        LISTING_FEE = "listing_fee", "Fee bidding creator"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    purpose = models.CharField(
        max_length=24,
        choices=Purpose.choices,
        default=Purpose.AUCTION_SETTLEMENT,
        db_index=True,
    )
    settlement = models.ForeignKey(
        AuctionSettlement,
        on_delete=models.PROTECT,
        related_name="gateway_attempts",
        blank=True,
        null=True,
    )
    listing_fee = models.ForeignKey(
        "payments.ListingFeeInvoice",
        on_delete=models.PROTECT,
        related_name="gateway_attempts",
        blank=True,
        null=True,
    )
    provider = models.CharField(
        max_length=24,
        choices=Provider.choices,
        default=Provider.XENDIT,
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
    invoice_id = models.CharField(max_length=120, blank=True, db_index=True)
    invoice_url = models.URLField(max_length=600, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True, db_index=True)
    payment_type = models.CharField(max_length=64, blank=True)
    gateway_status = models.CharField(max_length=32, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["settlement", "status"],
                name="payments_pa_settlem_721d18_idx",
            ),
            models.Index(
                fields=["provider", "order_id"],
                name="payments_pa_provide_c67606_idx",
            ),
        ]

    def __str__(self):
        return f"{self.order_id} — {self.get_status_display()}"

    @property
    def billable(self):
        """Objek yang ditagihkan: invoice lelang atau invoice fee listing."""
        if self.purpose == self.Purpose.LISTING_FEE:
            return self.listing_fee
        return self.settlement

    @property
    def payer(self):
        billable = self.billable
        if billable is None:
            return None
        if self.purpose == self.Purpose.LISTING_FEE:
            return billable.creator
        return billable.buyer

    @property
    def is_active(self):
        if self.status not in {self.Status.CREATED, self.Status.PENDING}:
            return False
        return not self.expires_at or timezone.now() < self.expires_at

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= Decimal("0.00"):
            errors["amount"] = "Nilai pembayaran harus lebih dari nol."
        if self.purpose == self.Purpose.LISTING_FEE:
            if not self.listing_fee_id:
                errors["listing_fee"] = "Tagihan fee listing wajib diisi."
            if self.settlement_id:
                errors["settlement"] = (
                    "Tagihan fee listing tidak boleh terhubung ke invoice lelang."
                )
            # Only enforce the amount-match check on creation (pk is None).
            if (
                self.pk is None
                and self.listing_fee_id
                and self.amount != self.listing_fee.total_amount
            ):
                errors["amount"] = (
                    "Nilai gateway harus sama dengan total fee listing."
                )
        else:
            if not self.settlement_id:
                errors["settlement"] = "Invoice lelang wajib diisi."
            if self.listing_fee_id:
                errors["listing_fee"] = (
                    "Invoice lelang tidak boleh terhubung ke tagihan fee listing."
                )
            # Only enforce the amount-match check on creation (pk is None).
            # Existing records must remain editable (e.g. admin status corrections)
            # even if the settlement amount was later adjusted.
            if (
                self.pk is None
                and self.settlement_id
                and self.amount != self.settlement.amount
            ):
                errors["amount"] = (
                    "Nilai gateway harus sama dengan invoice lelang."
                )
        if errors:
            raise ValidationError(errors)


class PlatformFeeSetting(models.Model):
    """Tarif fee bidding creator dan PPN yang berlaku di seluruh marketplace.

    Disimpan sebagai baris tunggal (singleton) supaya administrator dapat
    mengubah tarif tanpa deploy ulang. Nilai tarif ikut disalin ke setiap
    invoice saat dibuat, sehingga perubahan tarif tidak mengubah tagihan lama.
    """

    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    listing_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        help_text="Persentase fee bidding, dihitung dari harga awal (starting price).",
    )
    minimum_listing_fee = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("10000.00"),
        help_text="Fee minimum agar listing bernilai kecil tetap menutup biaya gateway.",
    )
    vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("11.00"),
        help_text="Tarif PPN yang ditambahkan ke fee creator dan invoice buyer.",
    )
    listing_fee_due_hours = models.PositiveIntegerField(
        default=48,
        help_text="Batas waktu pembayaran fee sebelum tagihan kedaluwarsa.",
    )
    auto_payout_enabled = models.BooleanField(
        default=False,
        help_text="Kirim payout ke creator otomatis setelah invoice buyer lunas.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Fee Setting"
        verbose_name_plural = "Platform Fee Settings"

    def __str__(self):
        return (
            f"Fee {self.listing_fee_percent}% + PPN {self.vat_percent}%"
        )

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Konfigurasi tarif platform tidak dapat dihapus.")

    @classmethod
    def load(cls):
        instance, _ = cls.objects.get_or_create(singleton_id=1)
        return instance

    def quote_listing_fee(self, starting_price: Decimal) -> dict:
        """Hitung rincian fee listing dari harga terendah yang dicantumkan creator."""
        base = quantize_money(starting_price or Decimal("0.00"))
        fee = quantize_money(base * (self.listing_fee_percent / Decimal(100)))
        if fee < self.minimum_listing_fee:
            fee = quantize_money(self.minimum_listing_fee)
        vat = quantize_money(fee * (self.vat_percent / Decimal(100)))
        return {
            "base_amount": base,
            "fee_percent": self.listing_fee_percent,
            "fee_amount": fee,
            "vat_percent": self.vat_percent,
            "vat_amount": vat,
            "total_amount": fee + vat,
        }


class ListingFeeInvoice(models.Model):
    """Tagihan fee bidding yang harus dilunasi creator sebelum listing tayang.

    Fee bersifat non-refundable: terjual atau tidak, creator tetap membayar
    fee beserta PPN-nya.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Menunggu pembayaran"
        PAID = "paid", "Lunas"
        EXPIRED = "expired", "Kedaluwarsa"
        CANCELLED = "cancelled", "Dibatalkan"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    invoice_number = models.CharField(max_length=40, unique=True, blank=True)
    nft = models.OneToOneField(
        NFTAsset,
        on_delete=models.CASCADE,
        related_name="listing_fee_invoice",
    )
    creator = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="listing_fee_invoices",
    )
    base_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Harga terendah (starting price) yang menjadi dasar perhitungan fee.",
    )
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=2)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=18, decimal_places=2)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    due_at = models.DateTimeField(db_index=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    payment_reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["creator", "status"])]

    def __str__(self):
        return self.invoice_number or str(self.public_id)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            date_part = timezone.now().strftime("%Y%m%d")
            self.invoice_number = f"BCFEE-{date_part}-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    @property
    def is_expired(self):
        return self.status == self.Status.PENDING and timezone.now() >= self.due_at

    def clean(self):
        errors = {}
        if self.total_amount is not None and self.total_amount <= Decimal("0.00"):
            errors["total_amount"] = "Total fee harus lebih dari nol."
        if (
            self.fee_amount is not None
            and self.vat_amount is not None
            and self.total_amount is not None
            and self.total_amount != self.fee_amount + self.vat_amount
        ):
            errors["total_amount"] = "Total fee harus sama dengan fee ditambah PPN."
        if self.nft_id and self.creator_id and self.nft.owner_id != self.creator_id:
            errors["creator"] = "Fee hanya dapat ditagihkan kepada pemilik NFT."
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

class PaymentGatewaySetting(models.Model):
    class Provider(models.TextChoices):
        XENDIT = "xendit", "Xendit"

    provider = models.CharField(
        max_length=24,
        choices=Provider.choices,
        default=Provider.XENDIT,
        unique=True,
    )

    enabled = models.BooleanField(default=False)

    is_production = models.BooleanField(
        default=False,
        help_text="Centang jika menggunakan Xendit Live API key.",
    )

    api_key = models.CharField(
        max_length=255,
        blank=True,
    )

    webhook_token = models.CharField(
        max_length=255,
        blank=True,
    )

    http_timeout = models.PositiveIntegerField(
        default=15,
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment Gateway Setting"
        verbose_name_plural = "Payment Gateway Settings"

    def __str__(self):
        return f"{self.get_provider_display()} Configuration"

class CreatorPayout(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    settlement = models.OneToOneField(
        AuctionSettlement,
        on_delete=models.PROTECT,
        related_name="creator_payout",
    )

    creator = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="creator_payouts",
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    bank_name = models.CharField(
        max_length=100,
        blank=True,
    )

    account_number = models.CharField(
        max_length=50,
        blank=True,
    )

    account_holder = models.CharField(
        max_length=150,
        blank=True,
    )

    reference_id = models.CharField(
        max_length=120,
        unique=True,
    )

    payout_reference = models.CharField(
        max_length=120,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    failure_reason = models.CharField(max_length=255, blank=True)

    response_payload = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference_id

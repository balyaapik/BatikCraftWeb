from decimal import Decimal
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        CREATOR = "creator", "Creator / User"
        BUYER = "buyer", "Buyer"

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.CREATOR,
    )
    display_name = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    wallet_address = models.CharField(max_length=128, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    @property
    def public_name(self):
        return self.display_name or self.get_full_name() or self.username


class BlogPost(models.Model):
    title = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    excerpt = models.TextField(max_length=320)
    content = models.TextField()
    cover_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog_detail", kwargs={"slug": self.slug})


class NFTAsset(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        LISTED = "listed", "Listed"
        AWAITING_PAYMENT = "awaiting_payment", "Awaiting payment"
        SOLD = "sold", "Sold"
        ARCHIVED = "archived", "Archived"

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="nfts",
        help_text="Creator asli NFT. Kepemilikan buyer disimpan di current_owner.",
    )
    current_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="owned_nfts",
        blank=True,
        null=True,
        help_text="Buyer yang menerima NFT setelah pembayaran dan mint selesai.",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="nfts/%Y/%m/",
        blank=True,
        null=True,
    )
    image_url = models.URLField(blank=True)
    source_project_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
    )
    source_app_version = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    token_id = models.CharField(max_length=128, blank=True)
    blockchain = models.CharField(max_length=64, blank=True)
    contract_address = models.CharField(max_length=128, blank=True)
    minted_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    starting_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    reserve_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        blank=True,
        null=True,
    )
    auction_starts_at = models.DateTimeField(blank=True, null=True)
    auction_ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "source_project_id"],
                condition=~models.Q(source_project_id=""),
                name="unique_owner_source_project",
            )
        ]

    def __str__(self):
        return self.title

    @property
    def display_image(self):
        if self.image:
            return self.image.url
        return self.image_url

    @property
    def highest_bid(self):
        return self.bids.order_by("-amount", "created_at").first()

    @property
    def current_price(self):
        highest = self.highest_bid
        return highest.amount if highest else self.starting_price

    @property
    def is_auction_open(self):
        now = timezone.now()
        if self.status != self.Status.LISTED:
            return False
        if self.auction_starts_at and now < self.auction_starts_at:
            return False
        if self.auction_ends_at and now >= self.auction_ends_at:
            return False
        return True

    @property
    def auction_has_ended(self):
        return bool(self.auction_ends_at and timezone.now() >= self.auction_ends_at)

    @property
    def reserve_met(self):
        highest = self.highest_bid
        if highest is None:
            return False
        return self.reserve_price is None or highest.amount >= self.reserve_price

    @property
    def collector(self):
        return self.current_owner

    def clean(self):
        if self.starting_price < 0:
            raise ValidationError(
                {"starting_price": "Harga awal tidak boleh negatif."}
            )
        if (
            self.auction_starts_at
            and self.auction_ends_at
            and self.auction_ends_at <= self.auction_starts_at
        ):
            raise ValidationError(
                {"auction_ends_at": "Waktu selesai harus setelah waktu mulai."}
            )


class Bid(models.Model):
    nft = models.ForeignKey(
        NFTAsset,
        on_delete=models.CASCADE,
        related_name="bids",
    )
    bidder = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bids",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-amount", "created_at"]
        indexes = [models.Index(fields=["nft", "-amount"])]

    def __str__(self):
        return f"{self.bidder.public_name} — {self.amount}"


class AuctionSettlement(models.Model):
    class Status(models.TextChoices):
        INVOICED = "invoiced", "Menunggu persetujuan buyer"
        ACCEPTED = "accepted", "Menunggu pembayaran"
        PAYMENT_SUBMITTED = "payment_submitted", "Pembayaran diajukan"
        MINTED = "minted", "Lunas dan NFT diterbitkan"
        DECLINED = "declined", "Ditolak buyer"
        EXPIRED = "expired", "Kedaluwarsa"
        CANCELLED = "cancelled", "Dibatalkan"

    class PaymentMethod(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Transfer bank"
        E_WALLET = "e_wallet", "Dompet digital"
        OTHER = "other", "Metode lain"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    invoice_number = models.CharField(max_length=40, unique=True, blank=True)
    nft = models.OneToOneField(
        NFTAsset,
        on_delete=models.PROTECT,
        related_name="settlement",
    )
    winning_bid = models.OneToOneField(
        Bid,
        on_delete=models.PROTECT,
        related_name="settlement",
    )
    creator = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="auction_sales",
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="auction_purchases",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.INVOICED,
        db_index=True,
    )
    payment_method = models.CharField(
        max_length=24,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
    )
    payment_instructions = models.TextField()
    payment_due_at = models.DateTimeField(db_index=True)
    payment_reference = models.CharField(max_length=160, blank=True)
    payment_proof = models.FileField(
        upload_to="payment-proofs/%Y/%m/",
        blank=True,
        null=True,
    )
    buyer_note = models.TextField(blank=True)
    review_note = models.TextField(blank=True)
    mint_reference = models.CharField(max_length=80, blank=True, unique=True, null=True)
    minted_to_wallet = models.CharField(max_length=128, blank=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    payment_submitted_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    minted_at = models.DateTimeField(blank=True, null=True)
    declined_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.invoice_number or str(self.public_id)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            date_part = timezone.now().strftime("%Y%m%d")
            self.invoice_number = f"BCINV-{date_part}-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return (
            self.status in {self.Status.INVOICED, self.Status.ACCEPTED}
            and timezone.now() >= self.payment_due_at
        )

    @property
    def is_complete(self):
        return self.status == self.Status.MINTED

    def clean(self):
        errors = {}
        if self.winning_bid_id and self.nft_id:
            if self.winning_bid.nft_id != self.nft_id:
                errors["winning_bid"] = "Bid pemenang harus berasal dari NFT yang sama."
        if self.winning_bid_id and self.buyer_id:
            if self.winning_bid.bidder_id != self.buyer_id:
                errors["buyer"] = "Buyer harus sama dengan bidder pemenang."
        if self.nft_id and self.creator_id:
            if self.nft.owner_id != self.creator_id:
                errors["creator"] = "Creator harus sama dengan pemilik awal NFT."
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Nilai invoice harus lebih dari nol."
        if errors:
            raise ValidationError(errors)


class ModelAsset(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        LISTED = "listed", "Listed"
        ARCHIVED = "archived", "Archived"

    class License(models.TextChoices):
        PERSONAL = "personal", "Personal"
        COMMERCIAL = "commercial", "Commercial"
        EXTENDED = "extended", "Extended Commercial"

    seller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="model_listings",
    )
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, default="ornament")
    source_model_id = models.CharField(
        max_length=160,
        blank=True,
        db_index=True,
    )
    source_app_version = models.CharField(max_length=32, blank=True)
    version = models.CharField(max_length=40, default="1.0.0")
    base_model_family = models.CharField(max_length=80, default="sdxl")
    trigger_words = models.JSONField(default=list, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    model_file = models.FileField(upload_to="models/%Y/%m/")
    preview = models.ImageField(
        upload_to="model-previews/%Y/%m/",
        blank=True,
        null=True,
    )
    preview_url = models.URLField(blank=True)
    price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    license_type = models.CharField(
        max_length=24,
        choices=License.choices,
        default=License.PERSONAL,
    )
    commercial_use = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["seller", "source_model_id", "version"],
                condition=~models.Q(source_model_id=""),
                name="unique_seller_model_version",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def display_preview(self):
        if self.preview:
            return self.preview.url
        return self.preview_url

    @property
    def sales_count(self):
        return self.purchases.filter(status=ModelPurchase.Status.PAID).count()

    def clean(self):
        if self.price < 0:
            raise ValidationError({"price": "Harga model tidak boleh negatif."})


class ModelPurchase(models.Model):
    class Status(models.TextChoices):
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    model = models.ForeignKey(
        ModelAsset,
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="model_purchases",
    )
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PAID,
        db_index=True,
    )
    license_snapshot = models.JSONField(default=dict, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["model", "buyer"],
                condition=models.Q(status="paid"),
                name="unique_paid_model_purchase",
            )
        ]

    def __str__(self):
        return f"{self.buyer.public_name} — {self.model.name}"

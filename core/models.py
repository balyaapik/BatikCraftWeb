from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        CREATOR = "creator", "Creator / User"
        BUYER = "buyer", "Buyer"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CREATOR)
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
        SOLD = "sold", "Sold"
        ARCHIVED = "archived", "Archived"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="nfts")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="nfts/%Y/%m/", blank=True, null=True)
    image_url = models.URLField(blank=True)
    source_project_id = models.CharField(max_length=128, blank=True, db_index=True)
    source_app_version = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    token_id = models.CharField(max_length=128, blank=True)
    blockchain = models.CharField(max_length=64, blank=True)
    contract_address = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    starting_price = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    reserve_price = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)
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

    def clean(self):
        if self.starting_price < 0:
            raise ValidationError({"starting_price": "Harga awal tidak boleh negatif."})
        if self.auction_starts_at and self.auction_ends_at and self.auction_ends_at <= self.auction_starts_at:
            raise ValidationError({"auction_ends_at": "Waktu selesai harus setelah waktu mulai."})


class Bid(models.Model):
    nft = models.ForeignKey(NFTAsset, on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bids")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-amount", "created_at"]
        indexes = [models.Index(fields=["nft", "-amount"])]

    def __str__(self):
        return f"{self.bidder.public_name} — {self.amount}"

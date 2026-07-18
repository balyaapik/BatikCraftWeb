import json
from decimal import Decimal
from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from rest_framework import serializers

from .models import Bid, ModelAsset, ModelPurchase, NFTAsset, User


class FormJSONField(serializers.JSONField):
    """A JSON field that also accepts multipart form values.

    ``multipart/form-data`` carries every value as a string, so a Studio
    client that uploads a ``.batikmodel`` file alongside ``trigger_words``
    cannot send a real JSON array. This field parses the string, and falls
    back to a comma separated list when the payload is plain text.
    """

    def __init__(self, *args, expect_list: bool = False, **kwargs):
        self.expect_list = expect_list
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                data = [] if self.expect_list else {}
            else:
                try:
                    data = json.loads(text)
                except ValueError:
                    if not self.expect_list:
                        raise serializers.ValidationError(
                            "Nilai harus berupa JSON yang valid."
                        )
                    data = [
                        item.strip()
                        for item in text.split(",")
                        if item.strip()
                    ]
        if self.expect_list and not isinstance(data, list):
            raise serializers.ValidationError("Nilai harus berupa daftar.")
        if not self.expect_list and not isinstance(data, dict):
            raise serializers.ValidationError("Nilai harus berupa objek JSON.")
        return super().to_internal_value(data)


class UserSerializer(serializers.ModelSerializer):
    public_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "role",
            "public_name",
            "bio",
            "wallet_address",
        )
        read_only_fields = ("id", "username", "role")


class BidSerializer(serializers.ModelSerializer):
    bidder_name = serializers.CharField(
        source="bidder.public_name",
        read_only=True,
    )

    class Meta:
        model = Bid
        fields = (
            "id",
            "nft",
            "bidder",
            "bidder_name",
            "amount",
            "created_at",
        )
        read_only_fields = (
            "id",
            "nft",
            "bidder",
            "bidder_name",
            "created_at",
        )

    def create(self, validated_data):
        nft = self.context["nft"]
        user = self.context["request"].user
        with transaction.atomic():
            locked = NFTAsset.objects.select_for_update().get(pk=nft.pk)
            if user.role != User.Role.BUYER:
                raise serializers.ValidationError(
                    "Hanya akun buyer yang dapat melakukan bidding."
                )
            if locked.owner_id == user.id:
                raise serializers.ValidationError(
                    "Pemilik NFT tidak dapat melakukan bid pada karyanya sendiri."
                )
            if not locked.is_auction_open:
                raise serializers.ValidationError(
                    "Auction belum dibuka atau sudah berakhir."
                )
            current = (
                locked.bids.aggregate(value=Max("amount"))["value"]
                or locked.starting_price
                or Decimal("0")
            )
            if validated_data["amount"] <= current:
                raise serializers.ValidationError(
                    {"amount": f"Bid harus lebih besar dari {current}."}
                )
            return Bid.objects.create(
                nft=locked,
                bidder=user,
                **validated_data,
            )


class NFTAssetSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(
        source="owner.public_name",
        read_only=True,
    )
    metadata = FormJSONField(required=False)
    # The partial unique constraint on (owner, source_project_id) makes DRF
    # mark this field required even though the model allows it to be blank.
    source_project_id = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
    )
    display_image = serializers.CharField(read_only=True)
    current_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )
    bid_count = serializers.IntegerField(
        source="bids.count",
        read_only=True,
    )
    is_auction_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = NFTAsset
        fields = (
            "id",
            "owner",
            "owner_name",
            "title",
            "description",
            "image",
            "image_url",
            "display_image",
            "source_project_id",
            "source_app_version",
            "metadata",
            "token_id",
            "blockchain",
            "contract_address",
            "status",
            "starting_price",
            "reserve_price",
            "current_price",
            "bid_count",
            "is_auction_open",
            "auction_starts_at",
            "auction_ends_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "owner",
            "status",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        self._validate_unique_source(attrs)
        starts = attrs.get(
            "auction_starts_at",
            getattr(self.instance, "auction_starts_at", None),
        )
        ends = attrs.get(
            "auction_ends_at",
            getattr(self.instance, "auction_ends_at", None),
        )
        if starts and ends and ends <= starts:
            raise serializers.ValidationError(
                {"auction_ends_at": "Waktu selesai harus setelah waktu mulai."}
            )
        return attrs

    def _validate_unique_source(self, attrs):
        source_id = attrs.get(
            "source_project_id",
            getattr(self.instance, "source_project_id", ""),
        )
        if not source_id:
            return
        request = self.context.get("request")
        owner = getattr(self.instance, "owner", None) or getattr(
            request, "user", None
        )
        if owner is None or not owner.is_authenticated:
            return
        duplicates = NFTAsset.objects.filter(
            owner=owner,
            source_project_id=source_id,
        )
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                {
                    "source_project_id": (
                        "Karya dengan source_project_id ini sudah ada di akunmu."
                    )
                }
            )


class ModelAssetSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(
        source="seller.public_name",
        read_only=True,
    )
    source_model_id = serializers.CharField(
        max_length=160,
        required=False,
        allow_blank=True,
    )
    trigger_words = FormJSONField(expect_list=True, required=False)
    capabilities = FormJSONField(expect_list=True, required=False)
    metadata = FormJSONField(required=False)
    display_preview = serializers.CharField(read_only=True)
    sales_count = serializers.IntegerField(read_only=True)
    owned = serializers.SerializerMethodField()

    class Meta:
        model = ModelAsset
        fields = (
            "id",
            "seller",
            "seller_name",
            "name",
            "description",
            "category",
            "source_model_id",
            "source_app_version",
            "version",
            "base_model_family",
            "trigger_words",
            "capabilities",
            "metadata",
            "model_file",
            "preview",
            "preview_url",
            "display_preview",
            "price",
            "license_type",
            "commercial_use",
            "status",
            "sales_count",
            "owned",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "seller",
            "status",
            "sales_count",
            "owned",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "model_file": {"write_only": True},
            "preview": {"write_only": True},
        }

    def get_owned(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        if obj.seller_id == request.user.id:
            return True
        return obj.purchases.filter(
            buyer=request.user,
            status=ModelPurchase.Status.PAID,
        ).exists()

    def validate(self, attrs):
        source_id = attrs.get(
            "source_model_id",
            getattr(self.instance, "source_model_id", ""),
        )
        version = attrs.get("version", getattr(self.instance, "version", ""))
        if source_id and version:
            request = self.context.get("request")
            seller = getattr(self.instance, "seller", None) or getattr(
                request, "user", None
            )
            if seller is not None and seller.is_authenticated:
                duplicates = ModelAsset.objects.filter(
                    seller=seller,
                    source_model_id=source_id,
                    version=version,
                )
                if self.instance is not None:
                    duplicates = duplicates.exclude(pk=self.instance.pk)
                if duplicates.exists():
                    raise serializers.ValidationError(
                        {
                            "source_model_id": (
                                "Model dengan source_model_id dan versi ini "
                                "sudah ada di akunmu."
                            )
                        }
                    )
        return attrs

    def validate_model_file(self, value):
        suffix = Path(value.name).suffix.casefold()
        if suffix != ".batikmodel":
            raise serializers.ValidationError(
                "File model harus memakai ekstensi .batikmodel."
            )
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Harga model tidak boleh negatif."
            )
        return value


class ModelPurchaseSerializer(serializers.ModelSerializer):
    model_name = serializers.CharField(
        source="model.name",
        read_only=True,
    )
    seller_name = serializers.CharField(
        source="model.seller.public_name",
        read_only=True,
    )
    version = serializers.CharField(
        source="model.version",
        read_only=True,
    )
    base_model_family = serializers.CharField(
        source="model.base_model_family",
        read_only=True,
    )
    trigger_words = serializers.JSONField(
        source="model.trigger_words",
        read_only=True,
    )
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ModelPurchase
        fields = (
            "id",
            "model",
            "model_name",
            "seller_name",
            "version",
            "base_model_family",
            "trigger_words",
            "amount_paid",
            "status",
            "license_snapshot",
            "download_count",
            "download_url",
            "purchased_at",
        )
        read_only_fields = fields

    def get_download_url(self, obj):
        request = self.context.get("request")
        path = reverse("api-model-download", args=[obj.model_id])
        if request is None:
            return path
        return request.build_absolute_uri(path)

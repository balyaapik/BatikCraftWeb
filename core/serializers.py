from decimal import Decimal
from django.db import transaction
from django.db.models import Max
from rest_framework import serializers
from .models import Bid, NFTAsset, User


class UserSerializer(serializers.ModelSerializer):
    public_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "role", "public_name", "bio", "wallet_address")
        read_only_fields = ("id", "username", "role")


class BidSerializer(serializers.ModelSerializer):
    bidder_name = serializers.CharField(source="bidder.public_name", read_only=True)

    class Meta:
        model = Bid
        fields = ("id", "nft", "bidder", "bidder_name", "amount", "created_at")
        read_only_fields = ("id", "nft", "bidder", "bidder_name", "created_at")

    def create(self, validated_data):
        nft = self.context["nft"]
        user = self.context["request"].user
        with transaction.atomic():
            locked = NFTAsset.objects.select_for_update().get(pk=nft.pk)
            if user.role != User.Role.BUYER:
                raise serializers.ValidationError("Hanya akun buyer yang dapat melakukan bidding.")
            if locked.owner_id == user.id:
                raise serializers.ValidationError("Pemilik NFT tidak dapat melakukan bid pada karyanya sendiri.")
            if not locked.is_auction_open:
                raise serializers.ValidationError("Auction belum dibuka atau sudah berakhir.")
            current = locked.bids.aggregate(value=Max("amount"))["value"] or locked.starting_price or Decimal("0")
            if validated_data["amount"] <= current:
                raise serializers.ValidationError({"amount": f"Bid harus lebih besar dari {current}."})
            return Bid.objects.create(nft=locked, bidder=user, **validated_data)


class NFTAssetSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.public_name", read_only=True)
    display_image = serializers.CharField(read_only=True)
    current_price = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    bid_count = serializers.IntegerField(source="bids.count", read_only=True)
    is_auction_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = NFTAsset
        fields = (
            "id", "owner", "owner_name", "title", "description", "image", "image_url", "display_image",
            "source_project_id", "source_app_version", "metadata", "token_id", "blockchain", "contract_address",
            "status", "starting_price", "reserve_price", "current_price", "bid_count", "is_auction_open",
            "auction_starts_at", "auction_ends_at", "created_at", "updated_at",
        )
        read_only_fields = ("id", "owner", "status", "created_at", "updated_at")

    def validate(self, attrs):
        starts = attrs.get("auction_starts_at", getattr(self.instance, "auction_starts_at", None))
        ends = attrs.get("auction_ends_at", getattr(self.instance, "auction_ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"auction_ends_at": "Waktu selesai harus setelah waktu mulai."})
        return attrs

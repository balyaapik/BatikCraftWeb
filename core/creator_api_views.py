"""Stricter NFT publish contract for creator marketplace listings."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .api_views import NFTAssetViewSet


class CreatorReadyNFTAssetViewSet(NFTAssetViewSet):
    """Ensure every published Studio listing can reach invoice settlement."""

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        nft = self.get_object()
        if not nft.auction_ends_at:
            now = timezone.now()
            nft.auction_starts_at = nft.auction_starts_at or now
            nft.auction_ends_at = max(nft.auction_starts_at, now) + timedelta(days=7)
            nft.save(
                update_fields=[
                    "auction_starts_at",
                    "auction_ends_at",
                    "updated_at",
                ]
            )
        if nft.auction_starts_at and nft.auction_ends_at <= nft.auction_starts_at:
            return Response(
                {"auction_ends_at": "Waktu selesai harus setelah waktu mulai."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if nft.reserve_price is not None and nft.reserve_price < nft.starting_price:
            return Response(
                {
                    "reserve_price": (
                        "Reserve price tidak boleh lebih rendah dari harga awal."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if nft.starting_price <= Decimal(0):
            return Response(
                {"starting_price": "Harga awal harus lebih dari nol."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().publish(request, pk=pk)

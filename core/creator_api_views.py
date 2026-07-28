"""Stricter NFT publish contract for creator marketplace listings."""

from decimal import Decimal

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .api_views import NFTAssetViewSet


class CreatorReadyNFTAssetViewSet(NFTAssetViewSet):
    """Reject listings that could never reach invoice settlement."""

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        nft = self.get_object()
        if not nft.auction_ends_at:
            return Response(
                {
                    "auction_ends_at": (
                        "Batas akhir lelang wajib diisi agar pemenang dapat ditagih."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
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

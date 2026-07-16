from decimal import Decimal
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import NFTAsset, User
from .serializers import BidSerializer, NFTAssetSerializer, UserSerializer


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, "action", None) == "create":
            return request.user.is_superuser or request.user.role == User.Role.CREATOR
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS or getattr(view, "action", None) == "bids":
            return True
        return request.user.is_superuser or obj.owner_id == request.user.id


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class NFTAssetViewSet(viewsets.ModelViewSet):
    serializer_class = NFTAssetSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    filterset_fields = []
    search_fields = []

    def get_queryset(self):
        qs = NFTAsset.objects.select_related("owner").prefetch_related("bids")
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.role == User.Role.CREATOR:
            return qs.filter(Q(owner=user) | Q(status=NFTAsset.Status.LISTED))
        return qs.filter(status=NFTAsset.Status.LISTED)

    def perform_create(self, serializer):
        if self.request.user.role != User.Role.CREATOR and not self.request.user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Hanya creator yang dapat mengunggah NFT.")
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        nft = self.get_object()
        if nft.owner_id != request.user.id and not request.user.is_superuser:
            return Response({"detail": "Hanya pemilik yang dapat mempublikasikan NFT."}, status=status.HTTP_403_FORBIDDEN)
        if nft.starting_price <= Decimal("0"):
            return Response({"starting_price": "Harga awal harus lebih dari nol."}, status=status.HTTP_400_BAD_REQUEST)
        if not nft.image and not nft.image_url:
            return Response({"image": "Unggah image atau isi image_url."}, status=status.HTTP_400_BAD_REQUEST)
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = timezone.now()
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        return Response(self.get_serializer(nft).data)

    @action(detail=True, methods=["get", "post"])
    def bids(self, request, pk=None):
        nft = self.get_object()
        if request.method == "GET":
            serializer = BidSerializer(nft.bids.select_related("bidder"), many=True)
            return Response(serializer.data)
        serializer = BidSerializer(data=request.data, context={"request": request, "nft": nft})
        serializer.is_valid(raise_exception=True)
        bid = serializer.save()
        return Response(BidSerializer(bid).data, status=status.HTTP_201_CREATED)

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ModelAsset, ModelPurchase, NFTAsset, User
from .serializers import (
    BidSerializer,
    ModelAssetSerializer,
    ModelPurchaseSerializer,
    NFTAssetSerializer,
    UserSerializer,
)


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, "action", None) == "create":
            return request.user.is_superuser or request.user.role == User.Role.CREATOR
        return True

    def has_object_permission(self, request, view, obj):
        if (
            request.method in permissions.SAFE_METHODS
            or getattr(view, "action", None) == "bids"
        ):
            return True
        return request.user.is_superuser or obj.owner_id == request.user.id


class IsModelSellerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, "action", None) == "create":
            return request.user.is_superuser or request.user.role == User.Role.CREATOR
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if getattr(view, "action", None) in {"purchase", "download"}:
            return True
        return request.user.is_superuser or obj.seller_id == request.user.id


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class StudioLogoutView(APIView):
    authentication_classes = [TokenAuthentication]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NFTAssetViewSet(viewsets.ModelViewSet):
    serializer_class = NFTAssetSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        qs = NFTAsset.objects.select_related("owner").prefetch_related("bids")
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.role == User.Role.CREATOR:
            return qs.filter(
                Q(owner=user) | Q(status=NFTAsset.Status.LISTED)
            )
        return qs.filter(status=NFTAsset.Status.LISTED)

    def perform_create(self, serializer):
        if (
            self.request.user.role != User.Role.CREATOR
            and not self.request.user.is_superuser
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Hanya creator yang dapat mengunggah NFT.")
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        nft = self.get_object()
        if nft.owner_id != request.user.id and not request.user.is_superuser:
            return Response(
                {"detail": "Hanya pemilik yang dapat mempublikasikan NFT."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if nft.starting_price <= Decimal("0"):
            return Response(
                {"starting_price": "Harga awal harus lebih dari nol."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not nft.image and not nft.image_url:
            return Response(
                {"image": "Unggah image atau isi image_url."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = timezone.now()
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        return Response(self.get_serializer(nft).data)

    @action(detail=True, methods=["get", "post"])
    def bids(self, request, pk=None):
        nft = self.get_object()
        if request.method == "GET":
            serializer = BidSerializer(
                nft.bids.select_related("bidder"),
                many=True,
            )
            return Response(serializer.data)
        serializer = BidSerializer(
            data=request.data,
            context={"request": request, "nft": nft},
        )
        serializer.is_valid(raise_exception=True)
        bid = serializer.save()
        return Response(
            BidSerializer(bid).data,
            status=status.HTTP_201_CREATED,
        )


class ModelAssetViewSet(viewsets.ModelViewSet):
    serializer_class = ModelAssetSerializer
    permission_classes = [permissions.IsAuthenticated, IsModelSellerOrReadOnly]

    def get_queryset(self):
        qs = ModelAsset.objects.select_related("seller").prefetch_related(
            "purchases"
        )
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(
            Q(status=ModelAsset.Status.LISTED) | Q(seller=user)
        )

    def perform_create(self, serializer):
        if (
            self.request.user.role != User.Role.CREATOR
            and not self.request.user.is_superuser
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Hanya creator yang dapat menjual model.")
        serializer.save(seller=self.request.user)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        model = self.get_object()
        if model.seller_id != request.user.id and not request.user.is_superuser:
            return Response(
                {"detail": "Hanya seller yang dapat mempublikasikan model."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not model.model_file:
            return Response(
                {"model_file": "File .batikmodel wajib diunggah."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if model.price < 0:
            return Response(
                {"price": "Harga model tidak boleh negatif."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        model.status = ModelAsset.Status.LISTED
        model.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(model).data)

    @action(detail=True, methods=["post"])
    def purchase(self, request, pk=None):
        model = self.get_object()
        if model.status != ModelAsset.Status.LISTED:
            return Response(
                {"detail": "Model belum tersedia untuk dibeli."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if model.seller_id == request.user.id:
            return Response(
                {"detail": "Seller tidak perlu membeli model miliknya sendiri."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            locked = ModelAsset.objects.select_for_update().get(pk=model.pk)
            purchase, created = ModelPurchase.objects.get_or_create(
                model=locked,
                buyer=request.user,
                status=ModelPurchase.Status.PAID,
                defaults={
                    "amount_paid": locked.price,
                    "license_snapshot": {
                        "license_type": locked.license_type,
                        "commercial_use": locked.commercial_use,
                        "model_version": locked.version,
                    },
                },
            )
        serializer = ModelPurchaseSerializer(
            purchase,
            context={"request": request},
        )
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        model = self.get_object()
        allowed = model.seller_id == request.user.id or request.user.is_superuser
        purchase = None
        if not allowed:
            purchase = ModelPurchase.objects.filter(
                model=model,
                buyer=request.user,
                status=ModelPurchase.Status.PAID,
            ).first()
            allowed = purchase is not None
        if not allowed:
            return Response(
                {"detail": "Beli model terlebih dahulu."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if purchase is not None:
            ModelPurchase.objects.filter(pk=purchase.pk).update(
                download_count=F("download_count") + 1
            )
        response = FileResponse(
            model.model_file.open("rb"),
            as_attachment=True,
            filename=model.model_file.name.rsplit("/", 1)[-1],
        )
        response["X-BatikCraft-Model-ID"] = str(model.pk)
        response["X-BatikCraft-Model-Version"] = model.version
        return response


class ModelLibraryView(generics.ListAPIView):
    serializer_class = ModelPurchaseSerializer

    def get_queryset(self):
        return ModelPurchase.objects.filter(
            buyer=self.request.user,
            status=ModelPurchase.Status.PAID,
        ).select_related("model", "model__seller")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

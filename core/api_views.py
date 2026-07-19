from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
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

_PACKAGE_METADATA_KEY = "_studio_source_package"
_ALLOWED_NFT_PACKAGE_SUFFIXES = {".batikcraftnft", ".batikpack"}
_DEFAULT_MAX_PACKAGE_SIZE = 512 * 1024 * 1024


def _is_creator(user) -> bool:
    """Creators and superusers may publish to the marketplaces."""

    return bool(user.is_superuser or user.role == User.Role.CREATOR)


def _package_record(nft: NFTAsset) -> dict:
    value = (nft.metadata or {}).get(_PACKAGE_METADATA_KEY, {})
    return value if isinstance(value, dict) else {}


def _package_storage_name(nft: NFTAsset) -> str:
    return str(_package_record(nft).get("storage_name") or "").strip()


def _delete_stored_package(nft: NFTAsset) -> None:
    storage_name = _package_storage_name(nft)
    if storage_name and default_storage.exists(storage_name):
        default_storage.delete(storage_name)


def _store_uploaded_package(nft: NFTAsset, upload) -> None:
    """Persist a Studio source package and record integrity metadata on the NFT."""

    suffix = Path(upload.name).suffix.casefold()
    if suffix not in _ALLOWED_NFT_PACKAGE_SUFFIXES:
        raise serializers.ValidationError(
            {
                "package_file": (
                    "Paket sumber harus memakai ekstensi .batikcraftnft atau .batikpack."
                )
            }
        )
    max_size = int(
        getattr(settings, "BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE", _DEFAULT_MAX_PACKAGE_SIZE)
    )
    if upload.size > max_size:
        raise serializers.ValidationError(
            {
                "package_file": (
                    f"Ukuran paket melebihi batas {max_size // (1024 * 1024)} MB."
                )
            }
        )

    previous = _package_storage_name(nft)
    storage_name = default_storage.save(
        f"nft-packages/{nft.owner_id}/{nft.pk}/{uuid.uuid4().hex}{suffix}",
        upload,
    )
    digest = hashlib.sha256()
    with default_storage.open(storage_name, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    metadata = dict(nft.metadata or {})
    metadata[_PACKAGE_METADATA_KEY] = {
        "storage_name": storage_name,
        "filename": Path(upload.name).name,
        "content_type": str(getattr(upload, "content_type", "") or ""),
        "size": int(upload.size),
        "sha256": digest.hexdigest(),
        "uploaded_at": timezone.now().isoformat(),
    }
    nft.metadata = metadata
    nft.save(update_fields=["metadata", "updated_at"])

    if previous and previous != storage_name and default_storage.exists(previous):
        default_storage.delete(previous)


def _can_download_package(nft: NFTAsset, user) -> bool:
    if not user or not user.is_authenticated or not _package_storage_name(nft):
        return False
    if user.is_superuser or nft.owner_id == user.id:
        return True

    auction_closed = nft.status == NFTAsset.Status.SOLD or (
        nft.auction_ends_at is not None and timezone.now() >= nft.auction_ends_at
    )
    if not auction_closed:
        return False
    winner = nft.highest_bid
    return winner is not None and winner.bidder_id == user.id


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, "action", None) == "create":
            return _is_creator(request.user)
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
            return _is_creator(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if getattr(view, "action", None) in {"purchase", "download"}:
            return True
        return request.user.is_superuser or obj.seller_id == request.user.id


class StudioCapabilitiesView(APIView):
    """Machine-readable contract used by BatikCraft Studio before integration work."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(
            {
                "api_version": "1.1",
                "minimum_studio_version": "0.2.0",
                "authentication": "token",
                "pagination": "page-number",
                "page_size": int(
                    getattr(settings, "REST_FRAMEWORK", {}).get("PAGE_SIZE", 20)
                ),
                "max_nft_package_bytes": int(
                    getattr(
                        settings,
                        "BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE",
                        _DEFAULT_MAX_PACKAGE_SIZE,
                    )
                ),
                "features": {
                    "profile": True,
                    "nft_marketplace": True,
                    "nft_bidding": True,
                    "nft_source_package_upload": True,
                    "nft_source_package_download": True,
                    "model_marketplace": True,
                    "model_purchase": True,
                    "model_download": True,
                    "model_library": True,
                },
            }
        )


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
        if not _is_creator(self.request.user):
            raise PermissionDenied("Hanya creator yang dapat mengunggah NFT.")
        nft = serializer.save(owner=self.request.user)
        upload = self.request.FILES.get("package_file")
        if upload is not None:
            try:
                _store_uploaded_package(nft, upload)
            except Exception:
                nft.delete()
                raise

    def perform_update(self, serializer):
        nft = serializer.save()
        upload = self.request.FILES.get("package_file")
        if upload is not None:
            _store_uploaded_package(nft, upload)

    def perform_destroy(self, instance):
        _delete_stored_package(instance)
        instance.delete()

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
        if (nft.metadata or {}).get("source_type") == "asset_library" and not _package_storage_name(nft):
            return Response(
                {"package_file": "Pustaka aset wajib menyertakan file .batikpack."},
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

    @action(detail=True, methods=["get"], url_path="package")
    def package(self, request, pk=None):
        nft = get_object_or_404(
            NFTAsset.objects.select_related("owner").prefetch_related("bids"),
            pk=pk,
        )
        if not _can_download_package(nft, request.user):
            return Response(
                {
                    "detail": (
                        "Paket hanya dapat diunduh oleh pemilik atau pemenang auction "
                        "setelah auction berakhir."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        record = _package_record(nft)
        storage_name = str(record.get("storage_name") or "")
        if not storage_name or not default_storage.exists(storage_name):
            return Response(
                {"detail": "Paket sumber tidak tersedia."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = FileResponse(
            default_storage.open(storage_name, "rb"),
            as_attachment=True,
            filename=str(record.get("filename") or Path(storage_name).name),
            content_type=str(record.get("content_type") or "application/octet-stream"),
        )
        response["X-BatikCraft-NFT-ID"] = str(nft.pk)
        response["X-BatikCraft-Package-SHA256"] = str(record.get("sha256") or "")
        return response


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
        if not _is_creator(self.request.user):
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
        if not model.model_file:
            return Response(
                {"detail": "File model tidak tersedia."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = FileResponse(
            model.model_file.open("rb"),
            as_attachment=True,
            filename=Path(model.model_file.name).name,
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

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.models import ListingFeeInvoice
from payments.services import (
    issue_listing_fee_invoice,
    listing_fee_is_paid,
    listing_fee_quote,
)

from .studio_package import (
    StudioPackageError,
    read_embedded_asset_pack,
    sha256_of_upload,
    verify_studio_package,
)

from .models import (
    AuctionSettlement,
    ModelAsset,
    ModelPurchase,
    NFTAsset,
    User,
)
from .serializers import (
    BidSerializer,
    ModelAssetSerializer,
    ModelPurchaseSerializer,
    NFTAssetSerializer,
    UserSerializer,
)

_PACKAGE_METADATA_KEY = "_studio_source_package"
_DOWNLOAD_PACKAGE_METADATA_KEY = "_studio_download_package"
_STUDIO_ORIGIN_METADATA_KEY = "_studio_origin"
_ALLOWED_NFT_PACKAGE_SUFFIXES = {".batikcraftnft"}
_DEFAULT_MAX_PACKAGE_SIZE = 512 * 1024 * 1024


def _fee_config():
    from payments.models import PlatformFeeSetting

    return PlatformFeeSetting.load()


def _fee_checkout_url(request, nft) -> str:
    return request.build_absolute_uri(
        reverse("payments:start_listing_fee_checkout", args=[nft.pk])
    )


def _listing_fee_payload(request, fee_invoice) -> dict:
    """Bentuk respons fee yang dikonsumsi BatikCraft Studio."""
    return {
        "nft_id": fee_invoice.nft_id,
        "status": fee_invoice.status,
        "invoice_number": fee_invoice.invoice_number,
        "currency": "IDR",
        "base_amount": str(fee_invoice.base_amount),
        "fee_percent": str(fee_invoice.fee_percent),
        "fee_amount": str(fee_invoice.fee_amount),
        "vat_percent": str(fee_invoice.vat_percent),
        "vat_amount": str(fee_invoice.vat_amount),
        "total_amount": str(fee_invoice.total_amount),
        "due_at": fee_invoice.due_at.isoformat() if fee_invoice.due_at else None,
        "paid_at": fee_invoice.paid_at.isoformat() if fee_invoice.paid_at else None,
        "checkout_url": _fee_checkout_url(request, fee_invoice.nft),
        "refundable": False,
    }


def _studio_origin_required() -> bool:
    """Marketplace hanya menerima karya dari paket BatikCraft Studio."""
    return bool(getattr(settings, "BATIKCRAFT_REQUIRE_STUDIO_PACKAGE", True))


def _verified_source_type(serializer, instance=None) -> tuple[str, dict]:
    metadata = serializer.validated_data.get(
        "metadata",
        getattr(instance, "metadata", None) or {},
    )
    metadata = metadata if isinstance(metadata, dict) else {}
    return str(metadata.get("source_type") or ""), metadata


def _verify_studio_origin(upload, image, serializer, instance=None):
    """Pastikan gambar NFT dan pustaka tertanam berasal dari envelope Studio."""
    if not _studio_origin_required():
        return None

    if str(serializer.validated_data.get("image_url", "") or "").strip():
        raise serializers.ValidationError(
            {
                "image_url": (
                    "Gambar NFT tidak boleh diambil dari URL luar. Unggah paket "
                    ".batikcraftnft dari BatikCraft Studio."
                )
            }
        )

    if upload is None:
        if image is not None:
            raise serializers.ValidationError(
                {
                    "package_file": (
                        "Gambar hanya diterima bersama paket .batikcraftnft dari "
                        "BatikCraft Studio."
                    )
                }
            )
        if instance is not None:
            return None
        raise serializers.ValidationError(
            {
                "package_file": (
                    "Karya baru wajib menyertakan paket .batikcraftnft yang "
                    "diekspor BatikCraft Studio."
                )
            }
        )

    if Path(upload.name).suffix.casefold() != ".batikcraftnft":
        raise serializers.ValidationError(
            {
                "package_file": (
                    "Unggah envelope .batikcraftnft bersegel. Pustaka .batikpack "
                    "harus berada di dalam envelope tersebut."
                )
            }
        )
    if image is None:
        raise serializers.ValidationError(
            {"image": "Sertakan preview dari paket sebagai gambar NFT."}
        )

    try:
        upload.seek(0)
        verified = verify_studio_package(upload)
    except StudioPackageError as exc:
        raise serializers.ValidationError({"package_file": str(exc)}) from exc
    finally:
        upload.seek(0)

    if sha256_of_upload(image) != verified.preview_sha256:
        raise serializers.ValidationError(
            {
                "image": (
                    "Gambar yang diunggah bukan preview dari paket tersebut. "
                    "Publikasikan langsung dari BatikCraft Studio."
                )
            }
        )

    source_type, metadata = _verified_source_type(serializer, instance)
    if source_type == "asset_library":
        if not verified.asset_pack_path:
            raise serializers.ValidationError(
                {
                    "package_file": (
                        "Listing pustaka wajib memuat tepat satu .batikpack "
                        "installable di dalam envelope bersegel."
                    )
                }
            )
        declared_path = str(metadata.get("embedded_asset_path") or "")
        declared_filename = str(metadata.get("embedded_asset_filename") or "")
        declared_sha256 = str(metadata.get("sha256") or "")
        mismatches = {}
        if declared_path and declared_path != verified.asset_pack_path:
            mismatches["embedded_asset_path"] = "Path pustaka tidak cocok dengan envelope."
        if declared_filename and declared_filename != verified.asset_pack_filename:
            mismatches["embedded_asset_filename"] = (
                "Nama pustaka tidak cocok dengan envelope."
            )
        if declared_sha256 and declared_sha256 != verified.asset_pack_sha256:
            mismatches["sha256"] = "Checksum pustaka tidak cocok dengan envelope."
        if mismatches:
            raise serializers.ValidationError({"metadata": mismatches})
    elif verified.asset_pack_path:
        raise serializers.ValidationError(
            {
                "metadata": {
                    "source_type": (
                        "Envelope memuat .batikpack tetapi metadata bukan asset_library."
                    )
                }
            }
        )
    return verified


def _record_studio_origin(nft: NFTAsset, verified) -> None:
    """Simpan jejak paket asal supaya dapat diaudit administrator."""
    metadata = dict(nft.metadata or {})
    origin = {
        "package_id": verified.package_id,
        "project_id": verified.project_id,
        "creator_user_id": verified.creator_user_id,
        "preview_sha256": verified.preview_sha256,
        "preview_size": verified.preview_size,
        "verified_at": timezone.now().isoformat(),
        # Segel paket hanya checksum; ini bukan bukti tanda tangan kriptografis.
        "signature_verified": False,
    }
    if verified.asset_pack_path:
        origin["asset_pack"] = {
            "path": verified.asset_pack_path,
            "filename": verified.asset_pack_filename,
            "sha256": verified.asset_pack_sha256,
            "size": verified.asset_pack_size,
            "pack_id": verified.asset_pack_id,
            "name": verified.asset_pack_name,
        }
    metadata[_STUDIO_ORIGIN_METADATA_KEY] = origin
    nft.metadata = metadata
    nft.save(update_fields=["metadata", "updated_at"])


def _is_creator(user) -> bool:
    """Creators and superusers may publish to the marketplaces."""

    return bool(user.is_superuser or user.role == User.Role.CREATOR)


def _package_record(nft: NFTAsset) -> dict:
    value = (nft.metadata or {}).get(_PACKAGE_METADATA_KEY, {})
    return value if isinstance(value, dict) else {}


def _download_package_record(nft: NFTAsset) -> dict:
    value = (nft.metadata or {}).get(_DOWNLOAD_PACKAGE_METADATA_KEY, {})
    if isinstance(value, dict) and value.get("storage_name"):
        return value
    return _package_record(nft)


def _package_storage_name(nft: NFTAsset) -> str:
    return str(_package_record(nft).get("storage_name") or "").strip()


def _download_package_storage_name(nft: NFTAsset) -> str:
    return str(_download_package_record(nft).get("storage_name") or "").strip()


def _delete_stored_package(nft: NFTAsset) -> None:
    names = {
        _package_storage_name(nft),
        _download_package_storage_name(nft),
    }
    for storage_name in names:
        if storage_name and default_storage.exists(storage_name):
            default_storage.delete(storage_name)


def _store_uploaded_package(nft: NFTAsset, upload, *, verified=None) -> None:
    """Simpan envelope audit dan `.batikpack` installable secara terpisah."""

    suffix = Path(upload.name).suffix.casefold()
    if suffix not in _ALLOWED_NFT_PACKAGE_SUFFIXES:
        raise serializers.ValidationError(
            {"package_file": "Paket sumber wajib berupa envelope .batikcraftnft."}
        )
    max_size = int(
        getattr(
            settings,
            "BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE",
            _DEFAULT_MAX_PACKAGE_SIZE,
        )
    )
    if upload.size > max_size:
        raise serializers.ValidationError(
            {
                "package_file": (
                    f"Ukuran paket melebihi batas "
                    f"{max_size // (1024 * 1024)} MB."
                )
            }
        )

    source_type = str((nft.metadata or {}).get("source_type") or "")
    embedded_content: bytes | None = None
    if source_type == "asset_library":
        if verified is None or not verified.asset_pack_path:
            raise serializers.ValidationError(
                {"package_file": "Envelope pustaka tidak memuat .batikpack terverifikasi."}
            )
        try:
            embedded_content = read_embedded_asset_pack(upload, verified)
        except StudioPackageError as exc:
            raise serializers.ValidationError({"package_file": str(exc)}) from exc

    previous_source = _package_storage_name(nft)
    previous_download = _download_package_storage_name(nft)
    source_storage_name = ""
    download_storage_name = ""
    created_names: list[str] = []
    try:
        upload.seek(0)
        source_storage_name = default_storage.save(
            f"nft-packages/{nft.owner_id}/{nft.pk}/{uuid.uuid4().hex}{suffix}",
            upload,
        )
        created_names.append(source_storage_name)
        digest = hashlib.sha256()
        with default_storage.open(source_storage_name, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)

        metadata = dict(nft.metadata or {})
        metadata[_PACKAGE_METADATA_KEY] = {
            "storage_name": source_storage_name,
            "filename": Path(upload.name).name,
            "content_type": str(getattr(upload, "content_type", "") or ""),
            "size": int(upload.size),
            "sha256": digest.hexdigest(),
            "uploaded_at": timezone.now().isoformat(),
            "kind": "sealed_listing_envelope",
        }

        if embedded_content is not None:
            download_storage_name = default_storage.save(
                (
                    f"asset-library-packages/{nft.owner_id}/{nft.pk}/"
                    f"{uuid.uuid4().hex}.batikpack"
                ),
                ContentFile(
                    embedded_content,
                    name=verified.asset_pack_filename or "pustaka.batikpack",
                ),
            )
            created_names.append(download_storage_name)
            metadata[_DOWNLOAD_PACKAGE_METADATA_KEY] = {
                "storage_name": download_storage_name,
                "filename": verified.asset_pack_filename,
                "content_type": "application/zip",
                "size": verified.asset_pack_size,
                "sha256": verified.asset_pack_sha256,
                "pack_id": verified.asset_pack_id,
                "name": verified.asset_pack_name,
                "extracted_from": source_storage_name,
                "kind": "installable_asset_pack",
            }
        else:
            metadata.pop(_DOWNLOAD_PACKAGE_METADATA_KEY, None)

        nft.metadata = metadata
        nft.save(update_fields=["metadata", "updated_at"])
    except Exception:
        for storage_name in created_names:
            if storage_name and default_storage.exists(storage_name):
                default_storage.delete(storage_name)
        raise

    old_names = {previous_source, previous_download} - {
        source_storage_name,
        download_storage_name,
        "",
    }
    for storage_name in old_names:
        if default_storage.exists(storage_name):
            default_storage.delete(storage_name)


def _can_download_package(nft: NFTAsset, user) -> bool:
    """Only the creator or the paid, minted owner may download source files."""

    if not user or not user.is_authenticated or not _download_package_storage_name(nft):
        return False
    if user.is_superuser or nft.owner_id == user.id:
        return True
    if nft.status != NFTAsset.Status.SOLD or nft.current_owner_id != user.id:
        return False
    settlement = getattr(nft, "settlement", None)
    return bool(
        settlement
        and settlement.status == AuctionSettlement.Status.MINTED
        and settlement.buyer_id == user.id
    )


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
                "api_version": "1.4",
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
                    "nft_auction_settlement": True,
                    "nft_payment_verification": True,
                    "nft_registry_mint": True,
                    "nft_owned_library": True,
                    "nft_source_package_upload": True,
                    "nft_source_package_download": True,
                    "nft_listing_fee": True,
                    "nft_listing_fee_vat": True,
                    "asset_library_sealed_envelope": True,
                    "asset_library_installable_download": True,
                    "creator_payout": True,
                    "model_marketplace": True,
                    "model_purchase": True,
                    "model_download": True,
                    "model_library": True,
                },
                "billing": {
                    "currency": "IDR",
                    "listing_fee_basis": "starting_price",
                    "listing_fee_refundable": False,
                    "listing_fee_percent": str(_fee_config().listing_fee_percent),
                    "minimum_listing_fee": str(_fee_config().minimum_listing_fee),
                    "vat_percent": str(_fee_config().vat_percent),
                    "vat_applies_to": ["listing_fee", "buyer_invoice"],
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
        qs = (
            NFTAsset.objects.select_related(
                "owner",
                "current_owner",
                "settlement",
            )
            .prefetch_related("bids")
        )
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.role == User.Role.CREATOR:
            return qs.filter(
                Q(owner=user) | Q(status=NFTAsset.Status.LISTED)
            )
        return qs.filter(
            Q(status=NFTAsset.Status.LISTED)
            | Q(current_owner=user, status=NFTAsset.Status.SOLD)
        )

    def perform_create(self, serializer):
        if not _is_creator(self.request.user):
            raise PermissionDenied("Hanya creator yang dapat mengunggah NFT.")
        upload = self.request.FILES.get("package_file")
        image = self.request.FILES.get("image")
        verified = _verify_studio_origin(upload, image, serializer)
        nft = serializer.save(owner=self.request.user)
        if verified is not None:
            _record_studio_origin(nft, verified)
        if upload is not None:
            try:
                _store_uploaded_package(nft, upload, verified=verified)
            except Exception:
                _delete_stored_package(nft)
                nft.delete()
                raise

    def perform_update(self, serializer):
        upload = self.request.FILES.get("package_file")
        image = self.request.FILES.get("image")
        verified = _verify_studio_origin(
            upload, image, serializer, instance=serializer.instance
        )
        nft = serializer.save()
        if verified is not None:
            _record_studio_origin(nft, verified)
        if upload is not None:
            _store_uploaded_package(nft, upload, verified=verified)

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
        if nft.status in {
            NFTAsset.Status.AWAITING_PAYMENT,
            NFTAsset.Status.SOLD,
        }:
            return Response(
                {
                    "detail": (
                        "NFT yang sedang ditagihkan atau sudah terjual tidak "
                        "dapat dipublikasikan ulang."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if nft.starting_price <= Decimal(0):
            return Response(
                {"starting_price": "Harga awal harus lebih dari nol."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not nft.image and not nft.image_url:
            return Response(
                {"image": "Unggah image atau isi image_url."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        source_type = (nft.metadata or {}).get("source_type")
        if source_type == "asset_library" and not _download_package_storage_name(nft):
            return Response(
                {
                    "package_file": (
                        "Pustaka aset wajib menyertakan .batikpack terverifikasi "
                        "di dalam envelope Studio."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not listing_fee_is_paid(nft):
            fee_invoice = issue_listing_fee_invoice(nft)
            return Response(
                {
                    "detail": (
                        "Fee bidding harus dilunasi sebelum NFT tayang di market."
                    ),
                    "listing_fee": _listing_fee_payload(request, fee_invoice),
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = timezone.now()
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        return Response(self.get_serializer(nft).data)

    @action(detail=True, methods=["get", "post"], url_path="listing-fee")
    def listing_fee(self, request, pk=None):
        """Lihat atau terbitkan tagihan fee bidding untuk satu NFT.

        GET mengembalikan estimasi bila tagihan belum ada, sehingga Studio bisa
        menampilkan biaya sebelum creator memutuskan untuk publish.
        """
        nft = self.get_object()
        if nft.owner_id != request.user.id and not request.user.is_superuser:
            return Response(
                {"detail": "Hanya pemilik yang dapat melihat fee NFT ini."},
                status=status.HTTP_403_FORBIDDEN,
            )
        existing = ListingFeeInvoice.objects.filter(nft=nft).first()
        if request.method == "GET" and existing is None:
            quote = listing_fee_quote(nft)
            return Response(
                {
                    "nft_id": nft.pk,
                    "status": "not_issued",
                    "currency": "IDR",
                    "base_amount": str(quote["base_amount"]),
                    "fee_percent": str(quote["fee_percent"]),
                    "fee_amount": str(quote["fee_amount"]),
                    "vat_percent": str(quote["vat_percent"]),
                    "vat_amount": str(quote["vat_amount"]),
                    "total_amount": str(quote["total_amount"]),
                    "checkout_url": _fee_checkout_url(request, nft),
                }
            )
        if nft.starting_price <= Decimal(0):
            return Response(
                {"starting_price": "Harga awal harus lebih dari nol."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fee_invoice = existing if request.method == "GET" else issue_listing_fee_invoice(nft)
        return Response(_listing_fee_payload(request, fee_invoice))

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
            NFTAsset.objects.select_related(
                "owner",
                "current_owner",
                "settlement",
            ).prefetch_related("bids"),
            pk=pk,
        )
        if not _can_download_package(nft, request.user):
            return Response(
                {
                    "detail": (
                        "Paket hanya dapat diunduh creator atau buyer setelah "
                        "pembayaran terverifikasi dan NFT selesai diterbitkan."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        record = _download_package_record(nft)
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
            content_type=str(
                record.get("content_type") or "application/octet-stream"
            ),
        )
        response["X-BatikCraft-NFT-ID"] = str(nft.pk)
        response["X-BatikCraft-Package-SHA256"] = str(
            record.get("sha256") or ""
        )
        response["X-BatikCraft-Package-Kind"] = str(record.get("kind") or "source")
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
            status=(
                status.HTTP_201_CREATED if created else status.HTTP_200_OK
            ),
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

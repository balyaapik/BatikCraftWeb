"""Zona waktu batas lelang dan pembatasan sumber gambar NFT."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import MarketplaceSetting, NFTAsset, User
from .studio_package import (
    StudioPackageError,
    read_embedded_asset_pack,
    verify_studio_package,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jpeg_preview() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 120, 40)).save(stream, format="JPEG")
    return stream.getvalue()


def build_asset_pack(*, malformed: bool = False) -> bytes:
    """Susun `.batikpack` kecil dengan struktur yang dibuat BatikCraft Studio."""
    asset_path = "assets/sekar-1.batikasset"
    asset_content = b"batikasset-test-payload"
    manifest = {
        "format": "format-salah" if malformed else "batikcraft-asset-pack",
        "schema_version": "1.0",
        "pack": {
            "id": "pustaka-sekar",
            "name": "Pustaka Sekar",
            "version": "1.0.0",
            "author": "Creator",
            "description": "Ornamen sekar",
        },
        "assets": [
            {
                "id": "sekar-1",
                "name": "Sekar Satu",
                "category": "ornamen",
                "file": asset_path,
                "tags": ["sekar"],
                "metadata": {},
            }
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(asset_path, asset_content)
    return buffer.getvalue()


def build_studio_package(
    preview: bytes,
    *,
    creator_user_id: str = "1",
    tamper_manifest: bool = False,
    drop_preview: bool = False,
    wrong_checksum: bool = False,
    asset_pack: bytes | None = None,
) -> bytes:
    """Susun paket .batikcraftnft bersegel seperti keluaran BatikCraft Studio."""
    project_json = json.dumps({"project": "demo"}).encode("utf-8")
    payload = {"preview.jpg": preview, "project/project.json": project_json}
    if asset_pack is not None:
        payload["project/library/pustaka-sekar.batikpack"] = asset_pack
    if drop_preview:
        payload.pop("preview.jpg")

    files = []
    for path, content in sorted(payload.items()):
        checksum = _sha256(content)
        if wrong_checksum and path == "preview.jpg":
            checksum = "0" * 64
        files.append(
            {
                "path": path,
                "role": (
                    "preview"
                    if path == "preview.jpg"
                    else "project-manifest"
                    if path == "project/project.json"
                    else "project-asset"
                ),
                "size": len(content),
                "sha256": checksum,
            }
        )

    manifest = {
        "format": "batikcraft-nft",
        "schema_version": "1.0",
        "package_id": "pkg-demo",
        "identity": {
            "project_id": "proj-demo",
            "title": "Sekar Jagad",
            "creator": {"user_id": creator_user_id, "display_name": "Creator"},
        },
        "files": files,
        "integrity": {"algorithm": "SHA-256", "digital_signature": False},
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    seal = {
        "format": "batikcraft-nft-seal",
        "schema_version": "1.0",
        "package_id": "pkg-demo",
        "manifest_sha256": _sha256(manifest_bytes),
    }
    if tamper_manifest:
        manifest["identity"]["title"] = "Judul Dipalsukan"
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("seal.json", json.dumps(seal, indent=2))
        for path, content in payload.items():
            archive.writestr(path, content)
    return buffer.getvalue()


class StudioPackageVerificationTests(TestCase):
    def test_valid_package_exposes_preview_fingerprint(self):
        preview = jpeg_preview()

        verified = verify_studio_package(io.BytesIO(build_studio_package(preview)))

        self.assertEqual(verified.preview_sha256, _sha256(preview))
        self.assertEqual(verified.project_id, "proj-demo")
        self.assertEqual(verified.title, "Sekar Jagad")

    def test_sealed_envelope_exposes_and_returns_installable_asset_pack(self):
        preview = jpeg_preview()
        asset_pack = build_asset_pack()
        package = io.BytesIO(build_studio_package(preview, asset_pack=asset_pack))

        verified = verify_studio_package(package)
        extracted = read_embedded_asset_pack(package, verified)

        self.assertEqual(
            verified.asset_pack_path,
            "project/library/pustaka-sekar.batikpack",
        )
        self.assertEqual(verified.asset_pack_filename, "pustaka-sekar.batikpack")
        self.assertEqual(verified.asset_pack_sha256, _sha256(asset_pack))
        self.assertEqual(verified.asset_pack_id, "pustaka-sekar")
        self.assertEqual(extracted, asset_pack)

    def test_malformed_embedded_asset_pack_is_rejected(self):
        package = build_studio_package(
            jpeg_preview(),
            asset_pack=build_asset_pack(malformed=True),
        )

        with self.assertRaises(StudioPackageError) as ctx:
            verify_studio_package(io.BytesIO(package))

        self.assertIn("Format asset pack", str(ctx.exception))

    def test_manifest_edited_after_sealing_is_rejected(self):
        package = build_studio_package(jpeg_preview(), tamper_manifest=True)

        with self.assertRaises(StudioPackageError) as ctx:
            verify_studio_package(io.BytesIO(package))

        self.assertIn("diubah setelah disegel", str(ctx.exception))

    def test_package_without_preview_is_rejected(self):
        package = build_studio_package(jpeg_preview(), drop_preview=True)

        with self.assertRaises(StudioPackageError):
            verify_studio_package(io.BytesIO(package))

    def test_checksum_mismatch_is_rejected(self):
        package = build_studio_package(jpeg_preview(), wrong_checksum=True)

        with self.assertRaises(StudioPackageError):
            verify_studio_package(io.BytesIO(package))

    def test_non_archive_is_rejected(self):
        with self.assertRaises(StudioPackageError):
            verify_studio_package(io.BytesIO(b"ini bukan zip"))

    def test_plain_zip_without_manifest_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("gambar.jpg", jpeg_preview())

        with self.assertRaises(StudioPackageError):
            verify_studio_package(io.BytesIO(buffer.getvalue()))


class StudioOriginAPITests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="origin-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        token = Token.objects.create(user=self.creator)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.preview = jpeg_preview()

    def _payload(self, package: bytes | None, image: bytes | None, **extra):
        data = {
            "title": "Sekar Jagad",
            "starting_price": "100000.00",
            **extra,
        }
        if package is not None:
            data["package_file"] = SimpleUploadedFile(
                "karya.batikcraftnft", package, content_type="application/zip"
            )
        if image is not None:
            data["image"] = SimpleUploadedFile(
                "preview.jpg", image, content_type="image/jpeg"
            )
        return data

    def test_upload_with_matching_package_is_accepted(self):
        package = build_studio_package(self.preview)

        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(package, self.preview),
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        nft = NFTAsset.objects.get(pk=response.data["id"])
        origin = nft.metadata["_studio_origin"]
        self.assertEqual(origin["preview_sha256"], _sha256(self.preview))
        self.assertEqual(origin["project_id"], "proj-demo")
        # Segel paket hanya checksum, bukan tanda tangan.
        self.assertFalse(origin["signature_verified"])

    def test_asset_library_without_embedded_pack_is_rejected(self):
        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(
                build_studio_package(self.preview),
                self.preview,
                metadata=json.dumps({"source_type": "asset_library"}),
            ),
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("package_file", response.data)

    def test_image_without_package_is_rejected(self):
        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(None, self.preview),
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("package_file", response.data)

    def test_image_that_is_not_the_package_preview_is_rejected(self):
        other = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 10, 10)).save(other, format="JPEG")

        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(build_studio_package(self.preview), other.getvalue()),
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("image", response.data)

    def test_external_image_url_is_rejected(self):
        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(
                build_studio_package(self.preview),
                self.preview,
                image_url="https://contoh.test/gambar.png",
            ),
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("image_url", response.data)

    def test_creating_without_any_package_is_rejected(self):
        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(None, None),
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("package_file", response.data)

    @override_settings(BATIKCRAFT_REQUIRE_STUDIO_PACKAGE=False)
    def test_restriction_can_be_disabled_for_migration(self):
        response = self.client.post(
            reverse("api-nft-list"),
            self._payload(None, self.preview),
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)


class MarketplaceTimezoneTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="tz-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )

    def test_default_marketplace_timezone_is_jakarta(self):
        self.assertEqual(MarketplaceSetting.load().default_timezone, "Asia/Jakarta")

    def test_setting_is_singleton(self):
        first = MarketplaceSetting.load()
        second = MarketplaceSetting.load()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MarketplaceSetting.objects.count(), 1)

    def test_user_without_preference_follows_marketplace_default(self):
        self.assertEqual(self.creator.active_timezone, "Asia/Jakarta")

    def test_user_preference_overrides_marketplace_default(self):
        self.creator.timezone_name = "Asia/Jayapura"
        self.creator.save(update_fields=["timezone_name"])

        self.assertEqual(self.creator.active_timezone, "Asia/Jayapura")

    def test_invalid_user_preference_falls_back_to_default(self):
        self.creator.timezone_name = "Mars/Olympus"
        self.creator.save(update_fields=["timezone_name"])

        self.assertEqual(self.creator.active_timezone, "Asia/Jakarta")

    def test_deadline_renders_in_each_users_own_timezone(self):
        """Satu instan UTC yang sama tampil sesuai zona waktu masing-masing."""
        instant = datetime(2026, 8, 1, 10, 0, tzinfo=ZoneInfo("UTC"))

        jakarta = instant.astimezone(ZoneInfo("Asia/Jakarta"))
        jayapura = instant.astimezone(ZoneInfo("Asia/Jayapura"))

        self.assertEqual(jakarta.strftime("%H:%M"), "17:00")
        self.assertEqual(jayapura.strftime("%H:%M"), "19:00")
        # Instan absolutnya tetap sama.
        self.assertEqual(jakarta, jayapura)

    def test_middleware_activates_user_timezone(self):
        from .timezone_middleware import ActiveTimezoneMiddleware

        self.creator.timezone_name = "Asia/Makassar"
        self.creator.save(update_fields=["timezone_name"])

        captured = {}

        def view(request):
            captured["tz"] = str(timezone.get_current_timezone())
            return "ok"

        class Req:
            user = self.creator

        ActiveTimezoneMiddleware(view)(Req())

        self.assertEqual(captured["tz"], "Asia/Makassar")
        # Zona waktu tidak boleh bocor ke request berikutnya.
        self.assertNotEqual(str(timezone.get_current_timezone()), "Asia/Makassar")

    def test_auction_deadline_with_offset_is_stored_as_utc(self):
        nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Parang",
            image_url="",
            starting_price=Decimal("100000.00"),
            auction_ends_at=datetime(
                2026, 8, 1, 17, 0, tzinfo=ZoneInfo("Asia/Jakarta")
            ),
        )
        nft.refresh_from_db()

        self.assertEqual(
            nft.auction_ends_at,
            datetime(2026, 8, 1, 10, 0, tzinfo=ZoneInfo("UTC")),
        )
        self.assertGreater(nft.auction_ends_at, timezone.now() - timedelta(days=3650))

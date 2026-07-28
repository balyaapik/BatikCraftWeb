from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from payments.models import ListingFeeInvoice

from .test_timezone_and_studio_origin import (
    build_asset_pack,
    build_studio_package,
    jpeg_preview,
)

from .models import AuctionSettlement, NFTAsset, User


def settle_listing_fee(nft) -> ListingFeeInvoice:
    """Lunasi fee bidding agar NFT dapat dipublikasikan dalam pengujian."""
    from payments.services import issue_listing_fee_invoice

    invoice = issue_listing_fee_invoice(nft)
    invoice.status = ListingFeeInvoice.Status.PAID
    invoice.paid_at = timezone.now()
    invoice.save(update_fields=["status", "paid_at", "updated_at"])
    return invoice


def valid_png_upload() -> SimpleUploadedFile:
    stream = BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(stream, format="PNG")
    return SimpleUploadedFile(
        "preview.png",
        stream.getvalue(),
        content_type="image/png",
    )


class StudioAPIContractTests(APITestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory(
            prefix="batikcraft-web-test-media-"
        )
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media.cleanup)

        self.creator = User.objects.create_user(
            username="studio_creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="studio_buyer",
            password="strong-pass-123",
            role=User.Role.BUYER,
        )
        self.creator_token = Token.objects.create(user=self.creator)
        self.buyer_token = Token.objects.create(user=self.buyer)
        self.asset_pack_bytes = b""

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def upload_library(self, *, suffix=".batikcraftnft", include_package=True):
        self.auth(self.creator_token)
        preview = jpeg_preview()
        self.asset_pack_bytes = build_asset_pack()
        embedded_sha256 = hashlib.sha256(self.asset_pack_bytes).hexdigest()
        payload = {
            "title": "Pustaka Ornamen Sekar",
            "description": "Pustaka aset dari BatikCraft Studio",
            "source_project_id": "asset-library-sekar-v1",
            "source_app_version": "0.2.0",
            "starting_price": "100000.00",
            "auction_ends_at": (
                timezone.now() + timedelta(hours=1)
            ).isoformat(),
            "metadata": json.dumps(
                {
                    "source_type": "asset_library",
                    "library_name": "Pustaka Ornamen Sekar",
                    "library_type": "ornamen",
                    "asset_count": 1,
                    "embedded_asset_path": (
                        "project/library/pustaka-sekar.batikpack"
                    ),
                    "embedded_asset_filename": "pustaka-sekar.batikpack",
                    "sha256": embedded_sha256,
                }
            ),
            "image": SimpleUploadedFile(
                "preview.jpg", preview, content_type="image/jpeg"
            ),
        }
        if include_package:
            payload["package_file"] = SimpleUploadedFile(
                f"sekar{suffix}",
                build_studio_package(preview, asset_pack=self.asset_pack_bytes),
                content_type="application/zip",
            )
        return self.client.post(
            reverse("api-nft-list"),
            payload,
            format="multipart",
        )

    def test_capabilities_describe_every_studio_marketplace_feature(self):
        self.client.credentials()
        response = self.client.get(reverse("api_capabilities"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["api_version"], "1.4")
        self.assertEqual(response.data["minimum_studio_version"], "0.2.0")
        self.assertTrue(response.data["features"]["nft_auction_settlement"])
        self.assertTrue(response.data["features"]["nft_payment_verification"])
        self.assertTrue(response.data["features"]["nft_registry_mint"])
        self.assertTrue(response.data["features"]["nft_owned_library"])
        self.assertTrue(response.data["features"]["nft_source_package_upload"])
        self.assertTrue(response.data["features"]["nft_source_package_download"])
        self.assertTrue(response.data["features"]["asset_library_sealed_envelope"])
        self.assertTrue(
            response.data["features"]["asset_library_installable_download"]
        )
        self.assertTrue(response.data["features"]["model_download"])
        self.assertTrue(response.data["features"]["nft_listing_fee"])
        self.assertTrue(response.data["features"]["creator_payout"])
        billing = response.data["billing"]
        self.assertEqual(billing["listing_fee_basis"], "starting_price")
        self.assertFalse(billing["listing_fee_refundable"])
        self.assertEqual(billing["vat_percent"], "11.00")

    def test_asset_library_package_is_persisted_published_and_downloadable(self):
        created = self.upload_library()
        self.assertEqual(created.status_code, 201, created.data)
        nft = NFTAsset.objects.get(pk=created.data["id"])
        source_record = nft.metadata["_studio_source_package"]
        download_record = nft.metadata["_studio_download_package"]
        self.assertEqual(source_record["filename"], "sekar.batikcraftnft")
        self.assertEqual(source_record["kind"], "sealed_listing_envelope")
        self.assertEqual(download_record["filename"], "pustaka-sekar.batikpack")
        self.assertEqual(download_record["kind"], "installable_asset_pack")
        self.assertEqual(
            download_record["sha256"],
            hashlib.sha256(self.asset_pack_bytes).hexdigest(),
        )

        # Publish ditolak selama fee bidding belum lunas.
        unpaid = self.client.post(
            reverse("api-nft-publish", args=[nft.pk]),
            {},
            format="json",
        )
        self.assertEqual(unpaid.status_code, 402, unpaid.data)
        self.assertEqual(unpaid.data["listing_fee"]["nft_id"], nft.pk)
        self.assertEqual(unpaid.data["listing_fee"]["fee_percent"], "5.00")
        self.assertEqual(unpaid.data["listing_fee"]["vat_percent"], "11.00")
        self.assertFalse(unpaid.data["listing_fee"]["refundable"])

        settle_listing_fee(nft)
        published = self.client.post(
            reverse("api-nft-publish", args=[nft.pk]),
            {},
            format="json",
        )
        self.assertEqual(published.status_code, 200, published.data)

        owner_download = self.client.get(
            reverse("api-nft-package", args=[nft.pk])
        )
        self.assertEqual(owner_download.status_code, 200)
        self.assertIn("pustaka-sekar.batikpack", owner_download["Content-Disposition"])
        self.assertEqual(
            owner_download["X-BatikCraft-Package-SHA256"],
            download_record["sha256"],
        )
        self.assertEqual(
            owner_download["X-BatikCraft-Package-Kind"],
            "installable_asset_pack",
        )
        self.assertEqual(b"".join(owner_download.streaming_content), self.asset_pack_bytes)

    def test_winning_bidder_downloads_package_only_after_paid_mint(self):
        created = self.upload_library()
        self.assertEqual(created.status_code, 201, created.data)
        expected_pack = self.asset_pack_bytes
        nft = NFTAsset.objects.get(pk=created.data["id"])
        settle_listing_fee(nft)
        self.client.post(
            reverse("api-nft-publish", args=[nft.pk]),
            {},
            format="json",
        )

        self.auth(self.buyer_token)
        bid_response = self.client.post(
            reverse("api-nft-bids", args=[nft.pk]),
            {"amount": "150000.00"},
            format="json",
        )
        self.assertEqual(bid_response.status_code, 201, bid_response.data)
        winning_bid = nft.bids.get(pk=bid_response.data["id"])

        before_end = self.client.get(
            reverse("api-nft-package", args=[nft.pk])
        )
        self.assertEqual(before_end.status_code, 403)

        now = timezone.now()
        NFTAsset.objects.filter(pk=nft.pk).update(
            auction_ends_at=now - timedelta(seconds=1)
        )
        after_end_unpaid = self.client.get(
            reverse("api-nft-package", args=[nft.pk])
        )
        self.assertEqual(after_end_unpaid.status_code, 403)

        settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=winning_bid,
            creator=self.creator,
            buyer=self.buyer,
            amount=winning_bid.amount,
            status=AuctionSettlement.Status.MINTED,
            payment_instructions="Transfer pengujian",
            payment_due_at=now + timedelta(days=1),
            paid_at=now,
            minted_at=now,
            mint_reference="BCMINT-CONTRACT-TEST",
        )
        NFTAsset.objects.filter(pk=nft.pk).update(
            status=NFTAsset.Status.SOLD,
            current_owner=self.buyer,
            minted_at=now,
            token_id="BC-CONTRACT-TEST",
            blockchain="BatikCraft Registry",
        )
        settlement.refresh_from_db()

        after_paid_mint = self.client.get(
            reverse("api-nft-package", args=[nft.pk])
        )
        self.assertEqual(after_paid_mint.status_code, 200)
        self.assertIn(".batikpack", after_paid_mint["Content-Disposition"])
        self.assertEqual(b"".join(after_paid_mint.streaming_content), expected_pack)

    def test_upload_without_sealed_package_is_rejected(self):
        """Gambar tanpa paket bersegel ditolak sejak pembuatan."""
        rejected = self.upload_library(include_package=False)

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("package_file", rejected.data)

    def test_batikpack_cannot_vouch_for_an_image(self):
        """`.batikpack` harus berada di dalam envelope yang mengikat preview."""
        rejected = self.upload_library(suffix=".batikpack")

        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("package_file", rejected.data)

    def test_invalid_package_extension_is_rejected_without_orphan_nft(self):
        before = NFTAsset.objects.count()
        rejected = self.upload_library(suffix=".zip")

        self.assertEqual(rejected.status_code, 400)
        self.assertIn("package_file", rejected.data)
        self.assertEqual(NFTAsset.objects.count(), before)

    def test_regular_nft_package_accepts_batikcraftnft(self):
        self.auth(self.creator_token)
        preview = jpeg_preview()
        created = self.client.post(
            reverse("api-nft-list"),
            {
                "title": "Motif Digital",
                "starting_price": str(Decimal("125000.00")),
                "metadata": json.dumps({"source_type": "motif_nft"}),
                "image": SimpleUploadedFile(
                    "preview.jpg", preview, content_type="image/jpeg"
                ),
                "package_file": SimpleUploadedFile(
                    "motif.batikcraftnft",
                    build_studio_package(preview),
                    content_type="application/zip",
                ),
            },
            format="multipart",
        )

        self.assertEqual(created.status_code, 201, created.data)
        nft = NFTAsset.objects.get(pk=created.data["id"])
        self.assertEqual(
            nft.metadata["_studio_source_package"]["filename"],
            "motif.batikcraftnft",
        )
        self.assertNotIn("_studio_download_package", nft.metadata)

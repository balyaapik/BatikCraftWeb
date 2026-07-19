from __future__ import annotations

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

from .models import NFTAsset, User


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
        self.media = tempfile.TemporaryDirectory(prefix="batikcraft-web-test-media-")
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

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def upload_library(self, *, suffix=".batikpack", include_package=True):
        self.auth(self.creator_token)
        payload = {
            "title": "Pustaka Ornamen Sekar",
            "description": "Pustaka aset dari BatikCraft Studio",
            "source_project_id": "asset-library-sekar-v1",
            "source_app_version": "0.2.0",
            "starting_price": "100000.00",
            "auction_ends_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            "metadata": json.dumps(
                {
                    "source_type": "asset_library",
                    "library_name": "Pustaka Ornamen Sekar",
                    "library_type": "ornamen",
                    "asset_count": 3,
                }
            ),
            "image": valid_png_upload(),
        }
        if include_package:
            payload["package_file"] = SimpleUploadedFile(
                f"sekar{suffix}",
                b"PK\x03\x04batik-pack-content",
                content_type="application/zip",
            )
        return self.client.post(reverse("api-nft-list"), payload, format="multipart")

    def test_capabilities_describe_every_studio_marketplace_feature(self):
        self.client.credentials()
        response = self.client.get(reverse("api_capabilities"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["api_version"], "1.1")
        self.assertEqual(response.data["minimum_studio_version"], "0.2.0")
        self.assertTrue(response.data["features"]["nft_source_package_upload"])
        self.assertTrue(response.data["features"]["nft_source_package_download"])
        self.assertTrue(response.data["features"]["model_download"])

    def test_asset_library_package_is_persisted_published_and_downloadable(self):
        created = self.upload_library()
        self.assertEqual(created.status_code, 201, created.data)
        nft = NFTAsset.objects.get(pk=created.data["id"])
        package_record = nft.metadata["_studio_source_package"]
        self.assertEqual(package_record["filename"], "sekar.batikpack")
        self.assertEqual(len(package_record["sha256"]), 64)

        published = self.client.post(
            reverse("api-nft-publish", args=[nft.pk]),
            {},
            format="json",
        )
        self.assertEqual(published.status_code, 200, published.data)

        owner_download = self.client.get(reverse("api-nft-package", args=[nft.pk]))
        self.assertEqual(owner_download.status_code, 200)
        self.assertIn("sekar.batikpack", owner_download["Content-Disposition"])
        self.assertEqual(
            owner_download["X-BatikCraft-Package-SHA256"],
            package_record["sha256"],
        )

    def test_winning_bidder_downloads_package_only_after_auction_closes(self):
        created = self.upload_library()
        self.assertEqual(created.status_code, 201, created.data)
        nft = NFTAsset.objects.get(pk=created.data["id"])
        self.client.post(reverse("api-nft-publish", args=[nft.pk]), {}, format="json")

        self.auth(self.buyer_token)
        bid = self.client.post(
            reverse("api-nft-bids", args=[nft.pk]),
            {"amount": "150000.00"},
            format="json",
        )
        self.assertEqual(bid.status_code, 201, bid.data)
        before_end = self.client.get(reverse("api-nft-package", args=[nft.pk]))
        self.assertEqual(before_end.status_code, 403)

        NFTAsset.objects.filter(pk=nft.pk).update(
            auction_ends_at=timezone.now() - timedelta(seconds=1)
        )
        after_end = self.client.get(reverse("api-nft-package", args=[nft.pk]))
        self.assertEqual(after_end.status_code, 200)

    def test_asset_library_publish_requires_batikpack(self):
        created = self.upload_library(include_package=False)
        self.assertEqual(created.status_code, 201, created.data)
        published = self.client.post(
            reverse("api-nft-publish", args=[created.data["id"]]),
            {},
            format="json",
        )
        self.assertEqual(published.status_code, 400)
        self.assertIn("package_file", published.data)

    def test_invalid_package_extension_is_rejected_without_orphan_nft(self):
        before = NFTAsset.objects.count()
        rejected = self.upload_library(suffix=".zip")

        self.assertEqual(rejected.status_code, 400)
        self.assertIn("package_file", rejected.data)
        self.assertEqual(NFTAsset.objects.count(), before)

    def test_regular_nft_package_accepts_batikcraftnft(self):
        self.auth(self.creator_token)
        created = self.client.post(
            reverse("api-nft-list"),
            {
                "title": "Motif Digital",
                "image_url": "https://example.com/motif.png",
                "starting_price": str(Decimal("125000.00")),
                "metadata": json.dumps({"source_type": "motif_nft"}),
                "package_file": SimpleUploadedFile(
                    "motif.batikcraftnft",
                    b"PK\x03\x04batikcraft-nft-content",
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

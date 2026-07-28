"""Regression tests for download access, HTTP methods, and multipart uploads."""

from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import ModelAsset, ModelPurchase, NFTAsset, User


def batikmodel_file(name="ornament.batikmodel"):
    return SimpleUploadedFile(name, b"PK\x03\x04batik", content_type="application/zip")


class ModelDownloadAccessTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username="dl_seller",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="dl_buyer",
            password="strong-pass-2026",
            role=User.Role.BUYER,
        )
        self.stranger = User.objects.create_user(
            username="dl_stranger",
            password="strong-pass-2026",
            role=User.Role.BUYER,
        )
        self.model = ModelAsset.objects.create(
            seller=self.seller,
            name="Ornamen Kawung",
            status=ModelAsset.Status.LISTED,
            price=Decimal("50000.00"),
            model_file=batikmodel_file(),
        )

    def test_download_streams_the_file_instead_of_redirecting_to_storage(self):
        ModelPurchase.objects.create(
            model=self.model,
            buyer=self.buyer,
            amount_paid=self.model.price,
        )
        self.client.force_login(self.buyer)
        response = self.client.get(
            reverse("model_download", args=[self.model.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertNotIn("Location", response)

    def test_download_counts_are_incremented_once_per_request(self):
        purchase = ModelPurchase.objects.create(
            model=self.model,
            buyer=self.buyer,
            amount_paid=self.model.price,
        )
        self.client.force_login(self.buyer)
        self.client.get(reverse("model_download", args=[self.model.pk]))
        purchase.refresh_from_db()

        self.assertEqual(purchase.download_count, 1)

    def test_a_user_without_a_purchase_cannot_download(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse("model_download", args=[self.model.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        response = self.client.get(
            reverse("model_download", args=[self.model.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


class WriteEndpointsRejectGetTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="method_creator",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
        )
        self.nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Sekar Jagad",
            image_url="https://example.com/sekar.png",
            starting_price=Decimal("1000.00"),
            auction_ends_at=timezone.now() + timedelta(days=1),
        )

    def test_publish_requires_post(self):
        self.client.force_login(self.creator)
        response = self.client.get(reverse("nft_publish", args=[self.nft.pk]))

        self.assertEqual(response.status_code, 405)

    def test_publish_without_paid_fee_keeps_nft_in_draft(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse("nft_publish", args=[self.nft.pk]))
        self.nft.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.nft.status, NFTAsset.Status.DRAFT)

    def test_publishing_is_still_possible_with_post(self):
        from core.tests import settle_listing_fee

        settle_listing_fee(self.nft)
        self.client.force_login(self.creator)
        response = self.client.post(reverse("nft_publish", args=[self.nft.pk]))
        self.nft.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.nft.status, NFTAsset.Status.LISTED)


class MultipartModelUploadTests(TestCase):
    """Studio uploads a file and its list fields in one multipart request."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="multipart_creator",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
        )
        self.api = APIClient()
        self.api.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.creator).key}"
        )

    def post_model(self, **overrides):
        payload = {
            "name": "Model Multipart",
            "category": "ornament",
            "version": "1.0.0",
            "base_model_family": "sdxl",
            "model_file": batikmodel_file(),
            "price": "1000.00",
        }
        payload.update(overrides)
        return self.api.post(reverse("api-model-list"), payload, format="multipart")

    def test_json_list_fields_are_parsed(self):
        response = self.post_model(
            trigger_words='["kawung", "parang"]',
            capabilities='["ornament", "tile"]',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["trigger_words"], ["kawung", "parang"])
        self.assertEqual(response.data["capabilities"], ["ornament", "tile"])

    def test_comma_separated_list_fields_are_parsed(self):
        response = self.post_model(
            trigger_words="kawung, parang",
            capabilities="ornament, tile",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["trigger_words"], ["kawung", "parang"])
        self.assertEqual(response.data["capabilities"], ["ornament", "tile"])

    def test_invalid_object_json_is_rejected(self):
        response = self.post_model(metadata="[1, 2]")

        self.assertEqual(response.status_code, 400)
        self.assertIn("metadata", response.data)

    @override_settings(BATIKCRAFT_REQUIRE_STUDIO_PACKAGE=False)
    def test_model_file_extension_is_required(self):
        response = self.post_model(model_file=batikmodel_file("model.zip"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("model_file", response.data)

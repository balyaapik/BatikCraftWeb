"""Regression tests for download access, HTTP methods, and multipart uploads."""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
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
        )

    def test_publish_requires_post(self):
        self.client.force_login(self.creator)
        response = self.client.get(reverse("nft_publish", args=[self.nft.pk]))

        self.assertEqual(response.status_code, 405)

    def test_publishing_is_still_possible_with_post(self):
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

    def test_json_encoded_list_fields_are_accepted(self):
        response = self.post_model(
            trigger_words='["bcr_kawung", "bcr_parang"]',
            capabilities='["ornament"]',
            metadata='{"source": "studio"}',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["trigger_words"], ["bcr_kawung", "bcr_parang"]
        )
        self.assertEqual(response.data["metadata"], {"source": "studio"})

    def test_comma_separated_list_fields_are_accepted(self):
        response = self.post_model(trigger_words="bcr_kawung, bcr_parang")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["trigger_words"], ["bcr_kawung", "bcr_parang"]
        )

    def test_malformed_metadata_is_rejected_with_a_field_error(self):
        response = self.post_model(metadata="not json at all")

        self.assertEqual(response.status_code, 400)
        self.assertIn("metadata", response.data)

    def test_the_file_extension_is_still_enforced(self):
        response = self.post_model(model_file=batikmodel_file("ornament.zip"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("model_file", response.data)


class OptionalSourceIdentifierTests(TestCase):
    """Studio identifiers are optional, but must stay unique per account."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="source_creator",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
        )
        self.api = APIClient()
        self.api.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.creator).key}"
        )

    def test_an_nft_can_be_created_without_a_source_project_id(self):
        response = self.api.post(
            reverse("api-nft-list"),
            {
                "title": "Manual Upload",
                "image_url": "https://example.com/manual.png",
                "starting_price": "1000.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_a_repeated_source_project_id_answers_with_a_field_error(self):
        payload = {
            "title": "Studio Upload",
            "image_url": "https://example.com/studio.png",
            "starting_price": "1000.00",
            "source_project_id": "project-001",
        }
        self.assertEqual(
            self.api.post(reverse("api-nft-list"), payload, format="json").status_code,
            201,
        )
        repeated = self.api.post(reverse("api-nft-list"), payload, format="json")

        self.assertEqual(repeated.status_code, 400)
        self.assertIn("source_project_id", repeated.data)

    def test_a_model_can_be_created_without_a_source_model_id(self):
        response = self.api.post(
            reverse("api-model-list"),
            {
                "name": "Manual Model",
                "version": "1.0.0",
                "model_file": batikmodel_file(),
                "price": "1000.00",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_a_repeated_model_id_and_version_answers_with_a_field_error(self):
        def upload():
            return self.api.post(
                reverse("api-model-list"),
                {
                    "name": "Studio Model",
                    "source_model_id": "model-001",
                    "version": "1.0.0",
                    "model_file": batikmodel_file(),
                    "price": "1000.00",
                },
                format="multipart",
            )

        self.assertEqual(upload().status_code, 201)
        repeated = upload()

        self.assertEqual(repeated.status_code, 400)
        self.assertIn("source_model_id", repeated.data)

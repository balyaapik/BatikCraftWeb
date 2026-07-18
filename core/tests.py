from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .captcha import CAPTCHA_SESSION_KEY, captcha_answer_for_nonce
from .models import Bid, ModelAsset, ModelPurchase, NFTAsset, User


class BatikCraftAPITests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer",
            password="strong-pass-123",
            role=User.Role.BUYER,
        )
        self.creator_token = Token.objects.create(user=self.creator)
        self.buyer_token = Token.objects.create(user=self.buyer)

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def captcha_answer(self):
        record = self.client.session[CAPTCHA_SESSION_KEY]
        return captcha_answer_for_nonce(record["nonce"])

    def test_registration_and_login_pages_render(self):
        self.client.credentials()
        register = self.client.get(reverse("register"))
        login = self.client.get(reverse("login"))

        self.assertEqual(register.status_code, 200)
        self.assertContains(register, "Buat akun")
        self.assertContains(register, 'id="id_captcha"')
        self.assertContains(register, reverse("captcha_image"))
        self.assertEqual(login.status_code, 200)
        self.assertContains(login, "Masuk ke BatikCraft")
        self.assertContains(login, 'id="id_captcha"')

    def test_captcha_image_is_svg_and_not_cacheable(self):
        response = self.client.get(reverse("captcha_image"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "<svg")

    def test_website_login_requires_correct_captcha(self):
        self.client.get(reverse("login"))
        rejected = self.client.post(
            reverse("login"),
            {
                "username": "creator",
                "password": "strong-pass-123",
                "captcha": "WRONG",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(rejected, "CAPTCHA salah")

        answer = self.captcha_answer()
        accepted = self.client.post(
            reverse("login"),
            {
                "username": "creator",
                "password": "strong-pass-123",
                "captcha": answer,
            },
        )
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.creator.pk)

    def test_registration_requires_correct_captcha(self):
        self.client.get(reverse("register"))
        answer = self.captcha_answer()
        response = self.client.post(
            reverse("register"),
            {
                "username": "newcreator",
                "email": "newcreator@example.com",
                "display_name": "New Creator",
                "role": User.Role.CREATOR,
                "password1": "A-strong-new-password-2026",
                "password2": "A-strong-new-password-2026",
                "captcha": answer,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newcreator").exists())

    def test_studio_login_and_profile(self):
        response = self.client.post(
            reverse("api_token"),
            {"username": "creator", "password": "strong-pass-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {response.data['token']}"
        )
        profile = self.client.get(reverse("api_me"))
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["username"], "creator")

    def test_creator_can_upload_and_publish_nft(self):
        self.auth(self.creator_token)
        response = self.client.post(
            reverse("api-nft-list"),
            {
                "title": "Mega Mendung Digital",
                "image_url": "https://example.com/batik.png",
                "starting_price": "100000.00",
                "source_project_id": "studio-project-001",
                "metadata": {"motif": "mega mendung"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        nft_id = response.data["id"]
        publish = self.client.post(
            reverse("api-nft-publish", args=[nft_id]),
            {},
            format="json",
        )
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.data["status"], NFTAsset.Status.LISTED)

    def test_buyer_bid_must_exceed_current_price(self):
        nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Parang",
            image_url="https://example.com/parang.png",
            status=NFTAsset.Status.LISTED,
            starting_price=Decimal("100.00"),
        )
        self.auth(self.buyer_token)
        first = self.client.post(
            reverse("api-nft-bids", args=[nft.pk]),
            {"amount": "150.00"},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        low = self.client.post(
            reverse("api-nft-bids", args=[nft.pk]),
            {"amount": "149.00"},
            format="json",
        )
        self.assertEqual(low.status_code, 400)
        self.assertEqual(Bid.objects.filter(nft=nft).count(), 1)

    def test_buyer_cannot_upload_nft(self):
        self.auth(self.buyer_token)
        response = self.client.post(
            reverse("api-nft-list"),
            {"title": "Tidak boleh"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_nft_detail_is_public(self):
        nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Truntum",
            image_url="https://example.com/truntum.png",
            status=NFTAsset.Status.LISTED,
            starting_price=Decimal("100.00"),
        )
        self.client.credentials()
        response = self.client.get(reverse("nft_detail", args=[nft.pk]))
        self.assertEqual(response.status_code, 200)

    def test_creator_can_publish_model_and_buyer_can_purchase(self):
        self.auth(self.creator_token)
        model_file = SimpleUploadedFile(
            "ornament.batikmodel",
            b"PK\x03\x04batik-model-test",
            content_type="application/zip",
        )
        created = self.client.post(
            reverse("api-model-list"),
            {
                "name": "Ornament Anggrek",
                "category": "ornament",
                "source_model_id": "ornament-anggrek-v1",
                "version": "1.0.0",
                "base_model_family": "sdxl",
                "trigger_words": ["bcr_anggrek"],
                "capabilities": ["ornament"],
                "model_file": model_file,
                "price": "75000.00",
            },
            format="multipart",
        )
        self.assertEqual(created.status_code, 201)
        model_id = created.data["id"]
        published = self.client.post(
            reverse("api-model-publish", args=[model_id]),
            {},
            format="json",
        )
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.data["status"], ModelAsset.Status.LISTED)

        self.auth(self.buyer_token)
        purchased = self.client.post(
            reverse("api-model-purchase", args=[model_id]),
            {},
            format="json",
        )
        self.assertEqual(purchased.status_code, 201)
        self.assertEqual(
            ModelPurchase.objects.filter(
                model_id=model_id,
                buyer=self.buyer,
                status=ModelPurchase.Status.PAID,
            ).count(),
            1,
        )
        library = self.client.get(reverse("api_model_library"))
        self.assertEqual(library.status_code, 200)
        self.assertEqual(len(library.data["results"]), 1)
        self.assertEqual(
            Path(library.data["results"][0]["download_url"]).name,
            "download",
        )

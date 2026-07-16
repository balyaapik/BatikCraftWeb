from decimal import Decimal
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from .models import Bid, NFTAsset, User


class BatikCraftAPITests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="strong-pass-123", role=User.Role.CREATOR)
        self.buyer = User.objects.create_user(username="buyer", password="strong-pass-123", role=User.Role.BUYER)
        self.creator_token = Token.objects.create(user=self.creator)
        self.buyer_token = Token.objects.create(user=self.buyer)

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_creator_can_upload_and_publish_nft(self):
        self.auth(self.creator_token)
        response = self.client.post(reverse("api-nft-list"), {
            "title": "Mega Mendung Digital",
            "image_url": "https://example.com/batik.png",
            "starting_price": "100000.00",
            "source_project_id": "studio-project-001",
            "metadata": {"motif": "mega mendung"},
        }, format="json")
        self.assertEqual(response.status_code, 201)
        nft_id = response.data["id"]
        publish = self.client.post(reverse("api-nft-publish", args=[nft_id]), {}, format="json")
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.data["status"], NFTAsset.Status.LISTED)

    def test_buyer_bid_must_exceed_current_price(self):
        nft = NFTAsset.objects.create(
            owner=self.creator, title="Parang", image_url="https://example.com/parang.png",
            status=NFTAsset.Status.LISTED, starting_price=Decimal("100.00")
        )
        self.auth(self.buyer_token)
        first = self.client.post(reverse("api-nft-bids", args=[nft.pk]), {"amount": "150.00"}, format="json")
        self.assertEqual(first.status_code, 201)
        low = self.client.post(reverse("api-nft-bids", args=[nft.pk]), {"amount": "149.00"}, format="json")
        self.assertEqual(low.status_code, 400)
        self.assertEqual(Bid.objects.filter(nft=nft).count(), 1)

    def test_buyer_cannot_upload_nft(self):
        self.auth(self.buyer_token)
        response = self.client.post(reverse("api-nft-list"), {"title": "Tidak boleh"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_nft_detail_is_public(self):
        nft = NFTAsset.objects.create(
            owner=self.creator, title="Truntum", image_url="https://example.com/truntum.png",
            status=NFTAsset.Status.LISTED, starting_price=Decimal("100.00")
        )
        self.client.credentials()
        response = self.client.get(reverse("nft_detail", args=[nft.pk]))
        self.assertEqual(response.status_code, 200)

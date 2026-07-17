from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import NFTAsset, User
from .ui_language import LANGUAGE_SESSION_KEY


class LibraryMarketAndLanguageTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="library_creator",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
            display_name="Library Creator",
        )
        self.artwork = NFTAsset.objects.create(
            owner=self.creator,
            title="Parang Digital",
            description="A complete digital artwork.",
            image_url="https://example.com/parang.png",
            status=NFTAsset.Status.LISTED,
            starting_price=Decimal("100000.00"),
            metadata={"source_type": "project"},
        )
        self.library_asset = NFTAsset.objects.create(
            owner=self.creator,
            title="Ornamen Anggrek",
            description="Reusable orchid ornament.",
            image_url="https://example.com/anggrek.png",
            status=NFTAsset.Status.LISTED,
            starting_price=Decimal("25000.00"),
            metadata={
                "source_type": "library_asset",
                "asset_category": "flora",
                "asset_name": "Anggrek",
                "license": "Commercial",
                "width": 1024,
                "height": 1024,
            },
        )

    def test_library_assets_are_separated_from_regular_nft_market(self):
        nft_market = self.client.get(reverse("market"))
        library_market = self.client.get(reverse("library_market"))

        self.assertEqual(nft_market.status_code, 200)
        self.assertContains(nft_market, self.artwork.title)
        self.assertNotContains(nft_market, self.library_asset.title)

        self.assertEqual(library_market.status_code, 200)
        self.assertContains(library_market, self.library_asset.title)
        self.assertNotContains(library_market, self.artwork.title)
        self.assertContains(library_market, "flora")
        self.assertContains(library_market, "Commercial")

    def test_library_market_searches_metadata_and_creator(self):
        by_category = self.client.get(reverse("library_market"), {"q": "flora"})
        by_license = self.client.get(reverse("library_market"), {"q": "Commercial"})
        by_creator = self.client.get(reverse("library_market"), {"q": "Library Creator"})

        self.assertContains(by_category, self.library_asset.title)
        self.assertContains(by_license, self.library_asset.title)
        self.assertContains(by_creator, self.library_asset.title)

    def test_home_features_library_assets_in_their_own_section(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.artwork.title)
        self.assertContains(response, self.library_asset.title)
        self.assertContains(response, reverse("library_market"))

    def test_language_switch_persists_english_in_session(self):
        default_page = self.client.get(reverse("home"))
        self.assertContains(default_page, '<html lang="id">', html=False)
        self.assertContains(default_page, "Market Pustaka")

        switched = self.client.post(
            reverse("set_ui_language"),
            {"language": "en", "next": reverse("library_market")},
        )
        self.assertRedirects(switched, reverse("library_market"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[LANGUAGE_SESSION_KEY], "en")

        english_page = self.client.get(reverse("library_market"))
        self.assertContains(english_page, '<html lang="en">', html=False)
        self.assertContains(english_page, "Library Market")
        self.assertContains(english_page, "Available Library Assets")
        self.assertContains(english_page, "Build faster.")

    def test_language_switch_rejects_unsafe_redirect_and_normalizes_value(self):
        response = self.client.post(
            reverse("set_ui_language"),
            {"language": "unsupported", "next": "https://attacker.invalid/path"},
        )

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[LANGUAGE_SESSION_KEY], "id")

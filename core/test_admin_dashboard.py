from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Bid, BlogPost, NFTAsset, User


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="strong-pass-123",
            email="admin@example.com",
            is_staff=True,
        )
        self.creator = User.objects.create_user(
            username="creator-admin-test",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer-admin-test",
            password="strong-pass-123",
            role=User.Role.BUYER,
        )
        self.post = BlogPost.objects.create(
            title="Draft Batik",
            slug="draft-batik",
            excerpt="Artikel draft untuk pengujian.",
            content="Konten artikel.",
        )
        self.nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Kawung Admin",
            image_url="https://example.com/kawung.png",
            starting_price=Decimal("100000.00"),
        )
        self.bid = Bid.objects.create(nft=self.nft, bidder=self.buyer, amount=Decimal("125000.00"))

    def test_non_staff_user_cannot_access_admin_dashboard(self):
        self.client.force_login(self.creator)
        response = self.client.get(reverse("admin_dashboard:home"))
        self.assertEqual(response.status_code, 403)

    def test_staff_user_can_access_admin_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selamat datang")
        self.assertContains(response, "Blog &amp; Post")

    def test_dashboard_router_sends_staff_to_admin_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard_router"))
        self.assertRedirects(response, reverse("admin_dashboard:home"))

    def test_admin_can_create_published_blog_post_with_generated_slug(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_dashboard:post_create"),
            {
                "title": "Warisan Batik Nusantara",
                "slug": "",
                "excerpt": "Cerita warisan batik Nusantara.",
                "content": "Isi artikel BatikCraft yang lengkap.",
                "cover_url": "https://example.com/cover.jpg",
                "is_published": "on",
                "published_at": "",
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard:post_list"))
        post = BlogPost.objects.get(title="Warisan Batik Nusantara")
        self.assertEqual(post.slug, "warisan-batik-nusantara")
        self.assertTrue(post.is_published)
        self.assertIsNotNone(post.published_at)

    def test_admin_can_toggle_blog_publish_status(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_dashboard:post_toggle_publish", args=[self.post.pk]))
        self.assertRedirects(response, reverse("admin_dashboard:post_list"))
        self.post.refresh_from_db()
        self.assertTrue(self.post.is_published)
        self.assertIsNotNone(self.post.published_at)

    def test_admin_can_edit_nft_status(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_dashboard:nft_edit", args=[self.nft.pk]),
            {
                "owner": self.creator.pk,
                "title": self.nft.title,
                "description": "Sudah dimoderasi admin.",
                "image_url": self.nft.image_url,
                "status": NFTAsset.Status.LISTED,
                "starting_price": "100000.00",
                "reserve_price": "",
                "auction_starts_at": "",
                "auction_ends_at": "",
                "token_id": "",
                "blockchain": "",
                "contract_address": "",
                "source_project_id": "",
                "source_app_version": "",
                "metadata": "{}",
            },
        )
        self.assertRedirects(response, reverse("admin_dashboard:nft_list"))
        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.LISTED)
        self.assertEqual(self.nft.description, "Sudah dimoderasi admin.")

    def test_admin_cannot_deactivate_current_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_dashboard:user_toggle_active", args=[self.admin.pk]))
        self.assertRedirects(response, reverse("admin_dashboard:user_list"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_can_delete_bid(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_dashboard:bid_delete", args=[self.bid.pk]))
        self.assertRedirects(response, reverse("admin_dashboard:bid_list"))
        self.assertFalse(Bid.objects.filter(pk=self.bid.pk).exists())

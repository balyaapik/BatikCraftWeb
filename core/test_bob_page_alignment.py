from django.test import TestCase
from django.urls import reverse

from .models import User


class BobPageAlignmentTests(TestCase):
    def test_auth_pages_use_bob_mock_structure(self):
        for name in ("login", "register"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "bob-auth-card")
            self.assertContains(response, "bob-page-refinement.css")
            self.assertContains(response, "bob-auth-brand")
            self.assertContains(response, 'id="captcha-image"')
            self.assertContains(response, 'id="id_captcha"')

    def test_creator_dashboard_uses_workspace_mock_structure(self):
        creator = User.objects.create_user(
            username="creator-mock",
            password="secret-pass-123",
            role=User.Role.CREATOR,
        )
        self.client.force_login(creator)
        response = self.client.get(reverse("creator_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bob-dashboard-shell")
        self.assertContains(response, "bob-stats-grid")
        self.assertContains(response, "bob-data-table")

    def test_buyer_dashboard_uses_workspace_mock_structure(self):
        buyer = User.objects.create_user(
            username="buyer-mock",
            password="secret-pass-123",
            role=User.Role.BUYER,
        )
        self.client.force_login(buyer)
        response = self.client.get(reverse("buyer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bob-nft-grid")
        self.assertContains(response, "bob-table-card")
        self.assertContains(response, "Buyer Dashboard")

    def test_admin_dashboard_uses_mock_brand_and_cards(self):
        admin = User.objects.create_superuser(
            username="admin-mock",
            password="secret-pass-123",
            email="admin@example.com",
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("admin_dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bob-admin-page")
        self.assertContains(response, "admin-brand")
        self.assertContains(response, "admin-stats-grid")
        self.assertContains(response, "admin-quick-grid")

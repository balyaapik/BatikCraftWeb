from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class AuthViewportTests(TestCase):
    """The auth pages render as a single centred card that fits the viewport."""

    def test_login_and_register_use_the_standalone_auth_card(self):
        login = self.client.get(reverse("login"))
        register = self.client.get(reverse("register"))

        for response in (login, register):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "css/bob-page-refinement.css")
            self.assertContains(response, 'class="bob-auth-wrap"')
            self.assertContains(response, "bob-auth-card")
            self.assertContains(response, 'class="bob-auth-form"')
            # The marketing shell is intentionally hidden on these pages.
            self.assertNotContains(response, 'class="header header-refined"')

    def test_auth_css_fits_the_card_to_short_viewports(self):
        css = (
            Path(settings.BASE_DIR)
            / "static"
            / "css"
            / "bob-page-refinement.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".bob-auth-wrap", css)
        self.assertIn("min-height: 100svh", css)
        self.assertIn("@media (max-height: 679px)", css)
        self.assertIn("@media (max-width: 580px)", css)

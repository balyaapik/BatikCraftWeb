"""The workspace, admin, and auth pages share the public site's theme."""

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from .models import User

CSS_DIR = Path(settings.BASE_DIR) / "static" / "css"


class LanguageSwitcherReachabilityTests(TestCase):
    """A signed-in user must still be able to change the interface language."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="theme_creator",
            password="strong-pass-2026",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="theme_buyer",
            password="strong-pass-2026",
            role=User.Role.BUYER,
        )
        self.admin = User.objects.create_superuser(
            username="theme_admin",
            password="strong-pass-2026",
            email="admin@example.com",
        )

    def assert_has_switcher(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("set_ui_language"))
        self.assertContains(response, 'name="language" value="id"')
        self.assertContains(response, 'name="language" value="en"')

    def test_public_pages_expose_the_switcher(self):
        self.assert_has_switcher(self.client.get(reverse("home")))

    def test_auth_pages_expose_the_switcher(self):
        self.assert_has_switcher(self.client.get(reverse("login")))
        self.assert_has_switcher(self.client.get(reverse("register")))

    def test_creator_dashboard_exposes_the_switcher(self):
        self.client.force_login(self.creator)
        self.assert_has_switcher(self.client.get(reverse("creator_dashboard")))

    def test_buyer_dashboard_exposes_the_switcher(self):
        self.client.force_login(self.buyer)
        self.assert_has_switcher(self.client.get(reverse("buyer_dashboard")))

    def test_admin_dashboard_exposes_the_switcher(self):
        self.client.force_login(self.admin)
        self.assert_has_switcher(self.client.get(reverse("admin_dashboard:home")))

    def test_the_switcher_markup_lives_in_a_single_partial(self):
        """Only the partial itself may build the language form."""

        templates = Path(settings.BASE_DIR) / "templates"
        partial = templates / "core" / "partials" / "language_switcher.html"
        offenders = [
            path.relative_to(templates).as_posix()
            for path in templates.rglob("*.html")
            if path != partial and 'name="language"' in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [])


class SharedPaletteTests(TestCase):
    """Workspace colours are aliases of the site tokens, not a second palette."""

    def setUp(self):
        self.workspace_css = (CSS_DIR / "bob-page-refinement.css").read_text(
            encoding="utf-8"
        )
        self.admin_css = (CSS_DIR / "admin-dashboard.css").read_text(
            encoding="utf-8"
        )

    def test_workspace_tokens_reference_the_site_tokens(self):
        for alias, token in (
            ("--bob-teal", "var(--teal)"),
            ("--bob-wine", "var(--wine)"),
            ("--bob-coral", "var(--coral)"),
            ("--bob-ink", "var(--ink)"),
            ("--bob-muted", "var(--muted)"),
        ):
            with self.subTest(token=alias):
                self.assertIn(f"{alias}: {token}", self.workspace_css)

    def test_the_grey_workspace_background_is_gone(self):
        for stale in ("#f5f3ee", "#f2f3ef"):
            with self.subTest(colour=stale):
                self.assertNotIn(stale, self.workspace_css)
                self.assertNotIn(stale, self.admin_css)

    def test_every_shell_uses_the_site_ivory(self):
        self.assertIn("background: var(--cream-2)", self.workspace_css)
        self.assertIn("background:var(--cream-2)", self.admin_css)

    def test_wordmarks_share_the_display_typeface(self):
        for css in (self.workspace_css, self.admin_css):
            with self.subTest(css=css[:40]):
                self.assertIn("Cinzel Decorative", css)
                self.assertIn("-.055em", css.replace("-0.055em", "-.055em"))

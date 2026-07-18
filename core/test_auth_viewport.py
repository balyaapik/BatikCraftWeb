from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class AuthViewportTests(TestCase):
    def test_login_and_register_load_viewport_fit_layout(self):
        login = self.client.get(reverse("login"))
        register = self.client.get(reverse("register"))

        self.assertEqual(login.status_code, 200)
        self.assertEqual(register.status_code, 200)
        self.assertContains(login, "css/auth-viewport.css")
        self.assertContains(register, "css/auth-viewport.css")
        self.assertContains(login, 'class="auth-fields-form auth-login-form"')
        self.assertContains(register, 'class="auth-fields-form auth-register-form"')

    def test_desktop_auth_css_prevents_normal_viewport_scrolling(self):
        css = (
            Path(settings.BASE_DIR) / "static" / "css" / "auth-viewport.css"
        ).read_text(encoding="utf-8")

        self.assertIn("(min-width: 681px) and (min-height: 680px)", css)
        self.assertIn("height: 100dvh", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn("(max-width: 680px), (max-height: 679px)", css)
        self.assertIn("overflow-y: auto", css)

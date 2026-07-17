from django.test import TestCase
from django.urls import reverse


class AuthLayoutTests(TestCase):
    def test_login_captcha_is_below_credentials(self):
        response = self.client.get(reverse("login"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index('id="id_password"'), html.index('id="captcha-image"'))
        self.assertLess(html.index('id="captcha-image"'), html.index('id="id_captcha"'))
        self.assertIn("@fortawesome/fontawesome-free", html)
        self.assertIn("fa-right-to-bracket", html)
        self.assertIn("fa-rotate-right", html)

    def test_register_captcha_is_below_account_fields(self):
        response = self.client.get(reverse("register"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index('id="id_password2"'), html.index('id="captcha-image"'))
        self.assertLess(html.index('id="captcha-image"'), html.index('id="id_captcha"'))
        self.assertIn("fa-user-plus", html)
        self.assertIn("fa-key", html)

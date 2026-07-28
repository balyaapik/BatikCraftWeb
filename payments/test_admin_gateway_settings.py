from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import User

from .models import PaymentGatewaySetting


@override_settings(SECURE_SSL_REDIRECT=False)
class PaymentGatewayAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="payment-admin",
            email="payment-admin@example.com",
            password="pass12345",
        )
        self.client.force_login(self.admin)
        self.url = reverse("admin_dashboard:payment_gateway_settings")

    def test_admin_can_open_payment_gateway_settings(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checkout Xendit")
        self.assertContains(response, reverse("payments:xendit_webhook"))

    def test_enabled_gateway_requires_api_key_and_webhook_token(self):
        response = self.client.post(
            self.url,
            {
                "enabled": "on",
                "http_timeout": "15",
                "api_key": "",
                "webhook_token": "",
                "action": "save",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "API key wajib diisi")
        self.assertContains(response, "Webhook verification token wajib diisi")
        self.assertFalse(PaymentGatewaySetting.objects.exists())

    def test_blank_secret_fields_preserve_existing_values(self):
        setting = PaymentGatewaySetting.objects.create(
            provider=PaymentGatewaySetting.Provider.XENDIT,
            enabled=True,
            is_production=False,
            api_key="xnd_development_existing-key",
            webhook_token="existing-webhook-token",
            http_timeout=15,
        )

        response = self.client.post(
            self.url,
            {
                "enabled": "on",
                "http_timeout": "20",
                "api_key": "",
                "webhook_token": "",
                "action": "save",
            },
        )

        self.assertRedirects(response, self.url)
        setting.refresh_from_db()
        self.assertEqual(setting.api_key, "xnd_development_existing-key")
        self.assertEqual(setting.webhook_token, "existing-webhook-token")
        self.assertEqual(setting.http_timeout, 20)

    def test_admin_can_remove_database_override_and_return_to_environment(self):
        PaymentGatewaySetting.objects.create(
            provider=PaymentGatewaySetting.Provider.XENDIT,
            enabled=False,
            api_key="",
            webhook_token="",
        )

        response = self.client.post(self.url, {"action": "reset_environment"})

        self.assertRedirects(response, self.url)
        self.assertFalse(PaymentGatewaySetting.objects.exists())

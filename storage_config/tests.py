import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import User

from .backends import DynamicMediaStorage
from .models import StorageConfiguration


class StorageConfigurationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="storage-admin",
            password="strong-pass-123",
            is_staff=True,
        )
        self.creator = User.objects.create_user(
            username="storage-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )

    def valid_payload(self, **overrides):
        payload = {
            "enabled": "on",
            "account_id": "0123456789abcdef0123456789abcdef",
            "endpoint_override": "",
            "access_key_id": "r2-access-key",
            "secret_access_key": "r2-secret-value",
            "bucket_name": "batikcraft-media",
            "location_prefix": "media",
            "use_signed_urls": "on",
            "signed_url_expiry": "900",
            "custom_domain": "",
            "action": "save",
        }
        payload.update(overrides)
        return payload

    def test_secret_is_encrypted_at_rest(self):
        configuration = StorageConfiguration.get_solo()
        configuration.set_secret_access_key("plain-secret")
        configuration.save()
        configuration.refresh_from_db()

        self.assertNotIn("plain-secret", configuration.secret_access_key_ciphertext)
        self.assertEqual(configuration.get_secret_access_key(), "plain-secret")

    def test_non_staff_cannot_open_storage_settings(self):
        self.client.force_login(self.creator)
        response = self.client.get(reverse("admin_dashboard:storage_settings"))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_save_r2_configuration(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_dashboard:storage_settings"),
            self.valid_payload(),
        )

        self.assertRedirects(response, reverse("admin_dashboard:storage_settings"))
        configuration = StorageConfiguration.get_solo()
        self.assertTrue(configuration.enabled)
        self.assertEqual(configuration.bucket_name, "batikcraft-media")
        self.assertEqual(configuration.updated_by, self.admin)
        self.assertEqual(configuration.get_secret_access_key(), "r2-secret-value")

    @patch("storage_config.views.test_r2_connection")
    def test_connection_must_succeed_before_save_test_persists(self, connection_test):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_dashboard:storage_settings"),
            self.valid_payload(action="save_test"),
        )

        self.assertRedirects(response, reverse("admin_dashboard:storage_settings"))
        connection_test.assert_called_once()
        self.assertTrue(StorageConfiguration.get_solo().enabled)

    def test_disabled_configuration_keeps_local_media_backend(self):
        StorageConfiguration.objects.create(singleton_id=1, enabled=False)
        with tempfile.TemporaryDirectory(prefix="batikcraft-local-media-") as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                storage = DynamicMediaStorage()
                saved_name = storage.save("checks/local.txt", ContentFile(b"local-media"))
                self.assertEqual(saved_name, "checks/local.txt")
                self.assertTrue(storage.exists(saved_name))
                self.assertEqual(
                    Path(media_root, "checks", "local.txt").read_bytes(),
                    b"local-media",
                )

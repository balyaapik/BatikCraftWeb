from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class FullFrameLayoutTests(TestCase):
    def test_bob_stylesheet_is_loaded_last(self):
        response = self.client.get(reverse("home"))
        html = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertLess(
            html.index("css/heritage-showcase.css"),
            html.index("css/fullframe-overrides.css"),
        )

    def test_mock_shell_is_fullframe_without_pink_gutter(self):
        css = (
            Path(settings.BASE_DIR) / "static" / "css" / "fullframe-overrides.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".site-shell", css)
        self.assertIn("width:100%", css)
        self.assertIn("max-width:none", css)
        self.assertIn("margin:0", css)
        self.assertIn("box-shadow:none", css)
        self.assertNotIn("background:#f7dcff", css)

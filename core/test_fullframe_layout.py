from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class FullFrameLayoutTests(TestCase):
    def test_public_pages_load_fullframe_override_last(self):
        response = self.client.get(reverse("home"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "css/fullframe-overrides.css")
        self.assertLess(
            html.index("css/heritage-showcase.css"),
            html.index("css/fullframe-overrides.css"),
        )

    def test_fullframe_override_removes_outer_gutter(self):
        css_path = Path(settings.BASE_DIR) / "static" / "css" / "fullframe-overrides.css"
        css = css_path.read_text(encoding="utf-8")

        self.assertIn(".site-shell", css)
        self.assertIn("width: 100%;", css)
        self.assertIn("max-width: none;", css)
        self.assertIn("margin: 0;", css)
        self.assertIn("box-shadow: none;", css)
        self.assertIn("background: var(--heritage-ivory, #fffaf0);", css)
        self.assertNotIn("#f1d9f5", css)
        self.assertNotIn("#f7dcff", css)

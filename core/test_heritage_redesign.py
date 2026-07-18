from django.test import TestCase
from django.urls import reverse

from .models import BlogPost


class BobMockVisualTests(TestCase):
    def test_home_uses_refined_header_without_promotional_topbar(self):
        response = self.client.get(reverse("home"))
        html = response.content.decode("utf-8")
        header = html.split('<header class="header header-refined"', 1)[1].split(
            "</header>", 1
        )[0]

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="site-shell"')
        self.assertContains(response, 'class="header header-refined"')
        self.assertContains(response, 'class="brand brand-lockup"')
        self.assertContains(response, 'class="brand-title">BatikCraft</span>')
        self.assertContains(response, "HERITAGE DIGITAL STUDIO")
        self.assertContains(response, "nav-dropdown")
        self.assertContains(response, reverse("market"))
        self.assertContains(response, reverse("library_market"))
        self.assertContains(response, reverse("model_market"))
        self.assertContains(response, reverse("download"))
        self.assertContains(response, reverse("app_page"))
        self.assertContains(response, reverse("documentation"))
        self.assertContains(response, 'class="hero-birds-asset"')
        self.assertNotIn(reverse("news"), header)
        # Documentation sits inside the Download dropdown, ahead of App.
        self.assertLess(
            header.index(reverse("download")), header.index(reverse("documentation"))
        )
        self.assertLess(
            header.index(reverse("documentation")), header.index(reverse("app_page"))
        )
        self.assertNotIn('class="topbar"', html)
        self.assertNotIn("Gratis Akses · Koleksi Baru · Edisi Warisan 2026", html)

    def test_news_and_blog_keep_database_content_in_bob_cards(self):
        post = BlogPost.objects.create(
            title="BatikCraft Studio Update",
            slug="studio-update",
            excerpt="A new Studio workflow.",
            content="The Studio receives a new workflow.",
            is_published=True,
        )
        news = self.client.get(reverse("news"))
        blog = self.client.get(reverse("blog_list"))
        self.assertContains(news, post.title)
        self.assertContains(news, 'class="editorial"')
        self.assertContains(blog, post.title)
        self.assertContains(blog, 'class="blog-grid"')
        self.assertContains(blog, 'class="blog-card"')

    def test_auth_uses_centered_responsive_card_and_real_captcha(self):
        for name in ("login", "register"):
            response = self.client.get(reverse(name))
            html = response.content.decode("utf-8")

            self.assertEqual(response.status_code, 200)
            self.assertIn('class="bob-auth-wrap"', html)
            self.assertIn("bob-auth-card", html)
            self.assertIn('class="bob-auth-card-head"', html)
            self.assertIn('class="bob-auth-form"', html)
            self.assertIn("HERITAGE DIGITAL STUDIO", html)
            self.assertLess(html.index('id="captcha-image"'), html.index('id="id_captcha"'))

        login_html = self.client.get(reverse("login")).content.decode("utf-8")
        self.assertLess(
            login_html.index('id="id_password"'), login_html.index('id="captcha-image"')
        )

    def test_download_page_links_all_native_platforms_to_latest_release(self):
        response = self.client.get(reverse("download"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="platform-download-grid"')
        self.assertIn("releases/latest/download", html)
        for filename in (
            "BatikCraftStudio-Setup-Windows-x64.exe",
            "BatikCraftStudio-Installer-Linux-x64.deb",
            "BatikCraftStudio-Installer-macOS-x64.dmg",
            "BatikCraftStudio-Installer-macOS-arm64.dmg",
        ):
            self.assertIn(filename, html)

    def test_documentation_page_is_public_and_linked(self):
        response = self.client.get(reverse("documentation"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="documentation-grid"')
        self.assertContains(response, "DESKTOP_BUILDS.md")
        self.assertContains(response, "PROJECT_FORMAT.md")
        self.assertContains(response, "docs/API.md")

    def test_market_pages_use_product_card_grid(self):
        for name in ("market", "library_market", "model_market"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'class="page-hero"')
            self.assertContains(response, 'class="market-grid"')

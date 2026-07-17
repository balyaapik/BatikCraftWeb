from django.test import TestCase
from django.urls import reverse

from .models import BlogPost


class HeritageVisualRedesignTests(TestCase):
    def test_home_loads_heritage_theme_and_showcase_sections(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "css/heritage-showcase.css")
        self.assertContains(response, "css/heritage-asset-cloud.css")
        self.assertContains(response, "css/heritage-asset-corner.css")
        self.assertContains(response, 'class="heritage-hero"')
        self.assertContains(response, 'class="heritage-collection"')
        self.assertContains(response, 'class="vendors-section"')
        self.assertContains(response, 'class="heritage-footer"')

    def test_news_page_renders_and_searches_published_posts(self):
        BlogPost.objects.create(
            title="BatikCraft Studio Update",
            slug="studio-update",
            excerpt="A new Studio workflow.",
            content="The Studio receives a new workflow.",
            is_published=True,
        )
        BlogPost.objects.create(
            title="Hidden Draft",
            slug="hidden-draft",
            excerpt="Not public.",
            content="Not public.",
            is_published=False,
        )

        response = self.client.get(reverse("news"), {"q": "Studio"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BatikCraft Studio Update")
        self.assertNotContains(response, "Hidden Draft")
        self.assertContains(response, 'class="news-layout"')

    def test_blog_search_uses_the_new_editorial_layout(self):
        BlogPost.objects.create(
            title="Cerita Mega Mendung",
            slug="cerita-mega-mendung",
            excerpt="Cerita dari Cirebon.",
            content="Sejarah dan proses kreatif Mega Mendung.",
            is_published=True,
        )

        response = self.client.get(reverse("blog_list"), {"q": "Mendung"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cerita Mega Mendung")
        self.assertContains(response, 'class="journal-showcase-grid"')

    def test_login_keeps_captcha_below_credentials_in_heritage_card(self):
        response = self.client.get(reverse("login"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="heritage-auth-card"', html)
        self.assertLess(html.index('id="id_password"'), html.index('id="captcha-image"'))
        self.assertLess(html.index('id="captcha-image"'), html.index('id="id_captcha"'))

    def test_navigation_exposes_news_and_all_three_markets(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, reverse("market"))
        self.assertContains(response, reverse("library_market"))
        self.assertContains(response, reverse("model_market"))
        self.assertContains(response, reverse("news"))

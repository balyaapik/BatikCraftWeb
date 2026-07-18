from django.test import TestCase
from django.urls import reverse

from .models import BlogPost


class BobMockVisualTests(TestCase):
    def test_home_uses_the_supplied_bob_mock_structure(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="site-shell"')
        self.assertContains(response, 'class="topbar"')
        self.assertContains(response, 'class="header"')
        self.assertContains(response, 'class="hero"')
        self.assertContains(response, 'class="hero-visual"')
        self.assertContains(response, 'class="collection-grid"')
        self.assertContains(response, 'class="vendor-grid"')
        self.assertContains(response, 'class="newsletter"')
        self.assertContains(response, 'class="footer"')

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

    def test_auth_uses_the_split_mock_card_and_real_captcha(self):
        response = self.client.get(reverse("login"))
        html = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="auth-page"', html)
        self.assertIn('class="auth-card"', html)
        self.assertIn('class="auth-copy"', html)
        self.assertIn('class="auth-form"', html)
        self.assertLess(html.index('id="id_password"'), html.index('id="captcha-image"'))
        self.assertLess(html.index('id="captcha-image"'), html.index('id="id_captcha"'))

    def test_market_pages_use_product_card_grid(self):
        for name in ("market", "library_market", "model_market"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'class="page-hero"')
            self.assertContains(response, 'class="market-grid"')

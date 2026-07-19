from django.contrib.auth import views as django_auth_views
from django.urls import include, path
from django.views.generic import TemplateView

from . import auth_views, public_views, views

urlpatterns = [
    path("", public_views.home, name="home"),
    path("download/", public_views.download_page, name="download"),
    path("app/", public_views.app_page, name="app_page"),
    path(
        "documentation/",
        TemplateView.as_view(template_name="core/documentation.html"),
        name="documentation",
    ),
    path("market/", public_views.nft_market, name="market"),
    path("market/<int:pk>/", public_views.nft_detail, name="nft_detail"),
    path("market/<int:pk>/bid/", views.place_bid, name="place_bid"),
    path(
        "market/<int:pk>/invoice/",
        views.create_auction_invoice,
        name="create_auction_invoice",
    ),
    path("library/", public_views.library_market, name="library_market"),
    path("models/", public_views.model_market, name="model_market"),
    path("models/<int:pk>/", public_views.model_detail, name="model_detail"),
    path(
        "models/<int:pk>/purchase/",
        views.model_purchase,
        name="model_purchase",
    ),
    path(
        "models/<int:pk>/download/",
        views.model_download,
        name="model_download",
    ),
    path("news/", public_views.news, name="news"),
    path("blog/", public_views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", public_views.blog_detail, name="blog_detail"),
    path("language/", public_views.set_ui_language, name="set_ui_language"),
    path("captcha/image/", auth_views.captcha_image, name="captcha_image"),
    path("login/", auth_views.CaptchaLoginView.as_view(), name="login"),
    path("logout/", django_auth_views.LogoutView.as_view(), name="logout"),
    path("register/", auth_views.register, name="register"),
    path("dashboard/", views.dashboard_router, name="dashboard_router"),
    path("dashboard/admin/", include("core.admin_urls")),
    path(
        "dashboard/creator/",
        views.creator_dashboard,
        name="creator_dashboard",
    ),
    path("dashboard/buyer/", views.buyer_dashboard, name="buyer_dashboard"),
    path("dashboard/profile/", views.profile_edit, name="profile_edit"),
    path("dashboard/nfts/new/", views.nft_create, name="nft_create"),
    path(
        "dashboard/nfts/<int:pk>/publish/",
        views.nft_publish,
        name="nft_publish",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/",
        views.settlement_detail,
        name="settlement_detail",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/accept/",
        views.accept_auction_invoice,
        name="accept_auction_invoice",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/decline/",
        views.decline_auction_invoice,
        name="decline_auction_invoice",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/payment/",
        views.submit_auction_payment,
        name="submit_auction_payment",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/verify/",
        views.verify_auction_payment,
        name="verify_auction_payment",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/reject-payment/",
        views.reject_auction_payment,
        name="reject_auction_payment",
    ),
    path(
        "dashboard/settlements/<uuid:public_id>/proof/",
        views.settlement_payment_proof,
        name="settlement_payment_proof",
    ),
    path("dashboard/models/new/", views.model_create, name="model_create"),
    path(
        "dashboard/models/<int:pk>/publish/",
        views.model_publish,
        name="model_publish",
    ),
]

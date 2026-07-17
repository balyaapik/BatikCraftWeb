from django.contrib.auth import views as django_auth_views
from django.urls import include, path

from . import auth_views, public_views, views

urlpatterns = [
    path("", public_views.home, name="home"),
    path("download/", views.download_page, name="download"),
    path("app/", views.app_page, name="app_page"),
    path("market/", public_views.nft_market, name="market"),
    path("market/<int:pk>/", views.nft_detail, name="nft_detail"),
    path("market/<int:pk>/bid/", views.place_bid, name="place_bid"),
    path("library/", public_views.library_market, name="library_market"),
    path("models/", views.model_market, name="model_market"),
    path("models/<int:pk>/", views.model_detail, name="model_detail"),
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
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),
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
    path("dashboard/models/new/", views.model_create, name="model_create"),
    path(
        "dashboard/models/<int:pk>/publish/",
        views.model_publish,
        name="model_publish",
    ),
]

from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("download/", views.download_page, name="download"),
    path("app/", views.app_page, name="app_page"),
    path("market/", views.market, name="market"),
    path("market/<int:pk>/", views.nft_detail, name="nft_detail"),
    path("market/<int:pk>/bid/", views.place_bid, name="place_bid"),
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard_router, name="dashboard_router"),
    path("dashboard/admin/", include("core.admin_urls")),
    path("dashboard/creator/", views.creator_dashboard, name="creator_dashboard"),
    path("dashboard/buyer/", views.buyer_dashboard, name="buyer_dashboard"),
    path("dashboard/profile/", views.profile_edit, name="profile_edit"),
    path("dashboard/nfts/new/", views.nft_create, name="nft_create"),
    path("dashboard/nfts/<int:pk>/publish/", views.nft_publish, name="nft_publish"),
]

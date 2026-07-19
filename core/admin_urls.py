from django.urls import path

from storage_config import views as storage_views

from . import admin_views

app_name = "admin_dashboard"

urlpatterns = [
    path("", admin_views.dashboard, name="home"),
    path("posts/", admin_views.post_list, name="post_list"),
    path("posts/new/", admin_views.post_create, name="post_create"),
    path("posts/<int:pk>/edit/", admin_views.post_edit, name="post_edit"),
    path("posts/<int:pk>/publish/", admin_views.post_toggle_publish, name="post_toggle_publish"),
    path("posts/<int:pk>/delete/", admin_views.post_delete, name="post_delete"),
    path("users/", admin_views.user_list, name="user_list"),
    path("users/<int:pk>/edit/", admin_views.user_edit, name="user_edit"),
    path("users/<int:pk>/active/", admin_views.user_toggle_active, name="user_toggle_active"),
    path("nfts/", admin_views.nft_list, name="nft_list"),
    path("nfts/<int:pk>/edit/", admin_views.nft_edit, name="nft_edit"),
    path("nfts/<int:pk>/delete/", admin_views.nft_delete, name="nft_delete"),
    path("bids/", admin_views.bid_list, name="bid_list"),
    path("bids/<int:pk>/delete/", admin_views.bid_delete, name="bid_delete"),
    path("storage/", storage_views.storage_settings, name="storage_settings"),
]

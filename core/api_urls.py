from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from .api_views import (
    MeView,
    ModelAssetViewSet,
    ModelLibraryView,
    NFTAssetViewSet,
    StudioLogoutView,
)

router = DefaultRouter()
router.register("nfts", NFTAssetViewSet, basename="api-nft")
router.register("models", ModelAssetViewSet, basename="api-model")

urlpatterns = [
    path("auth/token/", obtain_auth_token, name="api_token"),
    path("auth/logout/", StudioLogoutView.as_view(), name="api_logout"),
    path("me/", MeView.as_view(), name="api_me"),
    path("library/models/", ModelLibraryView.as_view(), name="api_model_library"),
    path("", include(router.urls)),
]

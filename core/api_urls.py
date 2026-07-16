from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter
from .api_views import MeView, NFTAssetViewSet

router = DefaultRouter()
router.register("nfts", NFTAssetViewSet, basename="api-nft")

urlpatterns = [
    path("auth/token/", obtain_auth_token, name="api_token"),
    path("me/", MeView.as_view(), name="api_me"),
    path("", include(router.urls)),
]

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic.base import RedirectView


class FaviconRedirectView(RedirectView):
    """Serve /favicon.ico for clients that ignore the <link rel="icon"> tags.

    The static URL is resolved per request, never at import time. In production
    the staticfiles backend is ``CompressedManifestStaticFilesStorage``, and
    looking a file up before ``collectstatic`` has run raises "Missing
    staticfiles manifest entry" — which would break ``collectstatic`` itself,
    because it loads the URLconf.

    The redirect is temporary on purpose. A permanent one would be cached by
    browsers indefinitely and would pin the hashed filename of today's icon.
    """

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return static_url("img/favicon/favicon.ico")


urlpatterns = [
    path("favicon.ico", FaviconRedirectView.as_view(), name="favicon"),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("api/v1/", include("core.api_urls")),
    path("payments/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

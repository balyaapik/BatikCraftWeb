from __future__ import annotations

from django.db.models import Count, Max, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import BlogPost, ModelAsset, NFTAsset, User
from .ui_language import LANGUAGE_SESSION_KEY, normalize_language

LIBRARY_SOURCE_TYPE = "library_asset"
REGULAR_NFT_FILTER = Q(metadata__source_type__isnull=True) | ~Q(
    metadata__source_type=LIBRARY_SOURCE_TYPE
)


def home(request: HttpRequest) -> HttpResponse:
    featured = (
        NFTAsset.objects.filter(
            REGULAR_NFT_FILTER,
            status=NFTAsset.Status.LISTED,
        )
        .select_related("owner")
        .annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))[:6]
    )
    featured_library = (
        NFTAsset.objects.filter(
            status=NFTAsset.Status.LISTED,
            metadata__source_type=LIBRARY_SOURCE_TYPE,
        )
        .select_related("owner")
        .annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))[:6]
    )
    featured_models = (
        ModelAsset.objects.filter(status=ModelAsset.Status.LISTED)
        .select_related("seller")[:6]
    )
    creators = (
        User.objects.filter(role=User.Role.CREATOR, is_active=True)
        .annotate(
            work_count=Count(
                "nfts",
                filter=Q(nfts__status=NFTAsset.Status.LISTED),
                distinct=True,
            ),
            model_count=Count(
                "model_listings",
                filter=Q(model_listings__status=ModelAsset.Status.LISTED),
                distinct=True,
            ),
        )
        .order_by("-work_count", "-model_count", "username")[:3]
    )
    posts = BlogPost.objects.filter(is_published=True)[:3]
    return render(
        request,
        "core/home.html",
        {
            "featured": featured,
            "featured_library": featured_library,
            "featured_models": featured_models,
            "creators": creators,
            "posts": posts,
        },
    )


def nft_market(request: HttpRequest) -> HttpResponse:
    items = (
        NFTAsset.objects.filter(
            REGULAR_NFT_FILTER,
            status=NFTAsset.Status.LISTED,
        )
        .select_related("owner")
        .annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))
    )
    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(owner__display_name__icontains=query)
            | Q(owner__username__icontains=query)
        )
    return render(
        request,
        "core/market.html",
        {"items": items, "query": query},
    )


def library_market(request: HttpRequest) -> HttpResponse:
    items = (
        NFTAsset.objects.filter(
            status=NFTAsset.Status.LISTED,
            metadata__source_type=LIBRARY_SOURCE_TYPE,
        )
        .select_related("owner")
        .annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))
    )
    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(owner__display_name__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(metadata__asset_category__icontains=query)
            | Q(metadata__asset_name__icontains=query)
            | Q(metadata__license__icontains=query)
        )
    return render(
        request,
        "core/library_market.html",
        {"items": items, "query": query},
    )


def blog_list(request: HttpRequest) -> HttpResponse:
    posts = BlogPost.objects.filter(is_published=True)
    query = request.GET.get("q", "").strip()
    if query:
        posts = posts.filter(
            Q(title__icontains=query)
            | Q(excerpt__icontains=query)
            | Q(content__icontains=query)
        )
    return render(
        request,
        "core/blog_list.html",
        {"posts": posts, "query": query},
    )


def news(request: HttpRequest) -> HttpResponse:
    posts = BlogPost.objects.filter(is_published=True)
    query = request.GET.get("q", "").strip()
    if query:
        posts = posts.filter(
            Q(title__icontains=query)
            | Q(excerpt__icontains=query)
            | Q(content__icontains=query)
        )
    return render(
        request,
        "core/news.html",
        {
            "featured_post": posts.first(),
            "posts": posts[1:7],
            "query": query,
        },
    )


@require_POST
def set_ui_language(request: HttpRequest) -> HttpResponse:
    request.session[LANGUAGE_SESSION_KEY] = normalize_language(
        request.POST.get("language")
    )
    request.session.modified = True

    next_url = request.POST.get("next", "").strip()
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("home")
    return redirect(next_url)

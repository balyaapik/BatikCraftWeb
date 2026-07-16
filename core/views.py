from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import role_required
from .forms import BidForm, NFTForm, ProfileForm, RegistrationForm
from .models import BlogPost, Bid, NFTAsset, User


def home(request):
    featured = NFTAsset.objects.filter(status=NFTAsset.Status.LISTED).select_related("owner").annotate(
        bid_count=Count("bids"), max_bid=Max("bids__amount")
    )[:6]
    posts = BlogPost.objects.filter(is_published=True)[:3]
    return render(request, "core/home.html", {"featured": featured, "posts": posts})


def download_page(request):
    return render(request, "core/download.html")


def app_page(request):
    return render(request, "core/app.html")


def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True)
    return render(request, "core/blog_list.html", {"posts": posts})


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    return render(request, "core/blog_detail.html", {"post": post})


def market(request):
    items = NFTAsset.objects.filter(status=NFTAsset.Status.LISTED).select_related("owner").annotate(
        bid_count=Count("bids"), max_bid=Max("bids__amount")
    )
    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(owner__display_name__icontains=query))
    return render(request, "core/market.html", {"items": items, "query": query})


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard_router")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Akun berhasil dibuat.")
        return redirect("dashboard_router")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard_router(request):
    if request.user.role == User.Role.BUYER:
        return redirect("buyer_dashboard")
    return redirect("creator_dashboard")


@role_required(User.Role.CREATOR)
def creator_dashboard(request):
    nfts = request.user.nfts.annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))
    stats = {
        "total": nfts.count(),
        "listed": nfts.filter(status=NFTAsset.Status.LISTED).count(),
        "total_bids": sum(n.bid_count for n in nfts),
    }
    return render(request, "core/creator_dashboard.html", {"nfts": nfts, "stats": stats})


@role_required(User.Role.BUYER)
def buyer_dashboard(request):
    market_items = NFTAsset.objects.filter(status=NFTAsset.Status.LISTED).select_related("owner").annotate(
        bid_count=Count("bids"), max_bid=Max("bids__amount")
    )[:12]
    own_bids = request.user.bids.select_related("nft", "nft__owner")[:10]
    return render(request, "core/buyer_dashboard.html", {"market_items": market_items, "own_bids": own_bids})


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil berhasil diperbarui.")
        return redirect("profile_edit")
    return render(request, "core/profile.html", {"form": form})


@role_required(User.Role.CREATOR)
def nft_create(request):
    form = NFTForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        nft = form.save(commit=False)
        nft.owner = request.user
        nft.save()
        messages.success(request, "NFT disimpan sebagai draft.")
        return redirect("creator_dashboard")
    return render(request, "core/nft_form.html", {"form": form, "title": "Tambah NFT"})


@role_required(User.Role.CREATOR)
def nft_publish(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    nft = get_object_or_404(NFTAsset, pk=pk, owner=request.user)
    if nft.starting_price <= Decimal("0"):
        messages.error(request, "Harga awal harus lebih dari nol sebelum NFT dipublikasikan.")
    elif not nft.image and not nft.image_url:
        messages.error(request, "NFT harus memiliki gambar sebelum dipublikasikan.")
    else:
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = timezone.now()
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        messages.success(request, "NFT berhasil ditayangkan di market.")
    return redirect("creator_dashboard")


def nft_detail(request, pk):
    nft = get_object_or_404(NFTAsset.objects.select_related("owner"), pk=pk)
    bid_form = BidForm()
    return render(request, "core/nft_detail.html", {"nft": nft, "bid_form": bid_form, "bids": nft.bids.select_related("bidder")[:20]})


@role_required(User.Role.BUYER)
def place_bid(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    form = BidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Nominal bid tidak valid.")
        return redirect("nft_detail", pk=pk)
    with transaction.atomic():
        nft = get_object_or_404(NFTAsset.objects.select_for_update(), pk=pk)
        if not nft.is_auction_open:
            messages.error(request, "Auction belum dibuka atau sudah berakhir.")
            return redirect("nft_detail", pk=pk)
        if nft.owner_id == request.user.id:
            messages.error(request, "Pemilik NFT tidak dapat melakukan bid pada karyanya sendiri.")
            return redirect("nft_detail", pk=pk)
        amount = form.cleaned_data["amount"]
        current = nft.bids.aggregate(value=Max("amount"))["value"] or nft.starting_price
        if amount <= current:
            messages.error(request, f"Bid harus lebih besar dari Rp{current:,.2f}.")
            return redirect("nft_detail", pk=pk)
        Bid.objects.create(nft=nft, bidder=request.user, amount=amount)
    messages.success(request, "Bid berhasil dikirim.")
    return redirect("nft_detail", pk=pk)

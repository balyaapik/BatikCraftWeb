from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .admin_forms import AdminBlogPostForm, AdminNFTForm, AdminUserForm
from .models import Bid, BlogPost, NFTAsset, User


def admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Halaman ini hanya dapat diakses administrator.")
        return view_func(request, *args, **kwargs)

    return wrapped


def paginate(request, queryset, per_page=15):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def build_unique_slug(post):
    base = slugify(post.slug or post.title)[:44] or "artikel"
    candidate = base
    number = 2
    queryset = BlogPost.objects.exclude(pk=post.pk)
    while queryset.filter(slug=candidate).exists():
        suffix = f"-{number}"
        candidate = f"{base[: 50 - len(suffix)]}{suffix}"
        number += 1
    return candidate


def save_blog_post(form):
    post = form.save(commit=False)
    post.slug = build_unique_slug(post)
    if post.is_published and not post.published_at:
        post.published_at = timezone.now()
    post.save()
    return post


@admin_required
def dashboard(request):
    post_counts = BlogPost.objects.aggregate(
        total=Count("id"),
        published=Count("id", filter=Q(is_published=True)),
        drafts=Count("id", filter=Q(is_published=False)),
    )
    nft_counts = NFTAsset.objects.aggregate(
        total=Count("id"),
        listed=Count("id", filter=Q(status=NFTAsset.Status.LISTED)),
        sold=Count("id", filter=Q(status=NFTAsset.Status.SOLD)),
    )
    bid_summary = Bid.objects.aggregate(total=Count("id"), value=Sum("amount"))
    stats = {
        "users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "posts": post_counts["total"],
        "published_posts": post_counts["published"],
        "draft_posts": post_counts["drafts"],
        "nfts": nft_counts["total"],
        "listed_nfts": nft_counts["listed"],
        "sold_nfts": nft_counts["sold"],
        "bids": bid_summary["total"],
        "bid_value": bid_summary["value"] or 0,
    }
    context = {
        "stats": stats,
        "recent_posts": BlogPost.objects.all()[:6],
        "recent_nfts": NFTAsset.objects.select_related("owner")[:6],
        "recent_bids": Bid.objects.select_related("nft", "bidder")[:6],
    }
    return render(request, "admin_dashboard/dashboard.html", context)


@admin_required
def post_list(request):
    posts = BlogPost.objects.all()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        posts = posts.filter(Q(title__icontains=query) | Q(excerpt__icontains=query) | Q(content__icontains=query))
    if status == "published":
        posts = posts.filter(is_published=True)
    elif status == "draft":
        posts = posts.filter(is_published=False)
    context = {"page_obj": paginate(request, posts), "query": query, "status": status}
    return render(request, "admin_dashboard/post_list.html", context)


@admin_required
def post_create(request):
    form = AdminBlogPostForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        post = save_blog_post(form)
        messages.success(request, f'Artikel "{post.title}" berhasil dibuat.')
        return redirect("admin_dashboard:post_list")
    return render(
        request,
        "admin_dashboard/form.html",
        {"form": form, "page_title": "Tulis Artikel", "section": "Blog", "submit_label": "Simpan Artikel"},
    )


@admin_required
def post_edit(request, pk):
    post = get_object_or_404(BlogPost, pk=pk)
    form = AdminBlogPostForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        post = save_blog_post(form)
        messages.success(request, f'Artikel "{post.title}" berhasil diperbarui.')
        return redirect("admin_dashboard:post_list")
    return render(
        request,
        "admin_dashboard/form.html",
        {
            "form": form,
            "page_title": "Edit Artikel",
            "section": "Blog",
            "submit_label": "Simpan Perubahan",
            "object": post,
        },
    )


@admin_required
@require_POST
def post_toggle_publish(request, pk):
    post = get_object_or_404(BlogPost, pk=pk)
    post.is_published = not post.is_published
    if post.is_published and not post.published_at:
        post.published_at = timezone.now()
    post.save(update_fields=["is_published", "published_at", "updated_at"])
    label = "dipublikasikan" if post.is_published else "dikembalikan menjadi draft"
    messages.success(request, f'Artikel "{post.title}" berhasil {label}.')
    return redirect("admin_dashboard:post_list")


@admin_required
def post_delete(request, pk):
    post = get_object_or_404(BlogPost, pk=pk)
    if request.method == "POST":
        title = post.title
        post.delete()
        messages.success(request, f'Artikel "{title}" berhasil dihapus.')
        return redirect("admin_dashboard:post_list")
    return render(
        request,
        "admin_dashboard/confirm_delete.html",
        {"object": post, "object_type": "artikel", "cancel_url": "admin_dashboard:post_list"},
    )


@admin_required
def user_list(request):
    users = User.objects.all().order_by("-date_joined")
    query = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    active = request.GET.get("active", "")
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(email__icontains=query)
        )
    if role in {User.Role.CREATOR, User.Role.BUYER}:
        users = users.filter(role=role)
    if active == "yes":
        users = users.filter(is_active=True)
    elif active == "no":
        users = users.filter(is_active=False)
    context = {
        "page_obj": paginate(request, users),
        "query": query,
        "role": role,
        "active": active,
        "roles": User.Role.choices,
    }
    return render(request, "admin_dashboard/user_list.html", context)


@admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = AdminUserForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if user.pk == request.user.pk:
            user.is_active = True
            user.is_staff = True
        user.save()
        messages.success(request, f'Pengguna "{user.username}" berhasil diperbarui.')
        return redirect("admin_dashboard:user_list")
    return render(
        request,
        "admin_dashboard/form.html",
        {
            "form": form,
            "page_title": "Edit Pengguna",
            "section": "Pengguna",
            "submit_label": "Simpan Pengguna",
            "object": target,
        },
    )


@admin_required
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "Akun administrator yang sedang digunakan tidak dapat dinonaktifkan.")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        state = "diaktifkan" if target.is_active else "dinonaktifkan"
        messages.success(request, f'Pengguna "{target.username}" berhasil {state}.')
    return redirect("admin_dashboard:user_list")


@admin_required
def nft_list(request):
    nfts = NFTAsset.objects.select_related("owner").annotate(bid_count=Count("bids"))
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        nfts = nfts.filter(
            Q(title__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(source_project_id__icontains=query)
            | Q(token_id__icontains=query)
        )
    if status in NFTAsset.Status.values:
        nfts = nfts.filter(status=status)
    context = {
        "page_obj": paginate(request, nfts),
        "query": query,
        "status": status,
        "statuses": NFTAsset.Status.choices,
    }
    return render(request, "admin_dashboard/nft_list.html", context)


@admin_required
def nft_edit(request, pk):
    nft = get_object_or_404(NFTAsset, pk=pk)
    form = AdminNFTForm(request.POST or None, request.FILES or None, instance=nft)
    if request.method == "POST" and form.is_valid():
        nft = form.save()
        messages.success(request, f'NFT "{nft.title}" berhasil diperbarui.')
        return redirect("admin_dashboard:nft_list")
    return render(
        request,
        "admin_dashboard/form.html",
        {
            "form": form,
            "page_title": "Edit NFT",
            "section": "NFT Market",
            "submit_label": "Simpan NFT",
            "object": nft,
            "multipart": True,
        },
    )


@admin_required
def nft_delete(request, pk):
    nft = get_object_or_404(NFTAsset, pk=pk)
    if request.method == "POST":
        title = nft.title
        nft.delete()
        messages.success(request, f'NFT "{title}" beserta bid terkait berhasil dihapus.')
        return redirect("admin_dashboard:nft_list")
    return render(
        request,
        "admin_dashboard/confirm_delete.html",
        {"object": nft, "object_type": "NFT", "cancel_url": "admin_dashboard:nft_list"},
    )


@admin_required
def bid_list(request):
    bids = Bid.objects.select_related("nft", "bidder")
    query = request.GET.get("q", "").strip()
    if query:
        bids = bids.filter(Q(nft__title__icontains=query) | Q(bidder__username__icontains=query))
    return render(
        request,
        "admin_dashboard/bid_list.html",
        {"page_obj": paginate(request, bids), "query": query},
    )


@admin_required
def bid_delete(request, pk):
    bid = get_object_or_404(Bid.objects.select_related("nft", "bidder"), pk=pk)
    if request.method == "POST":
        bid.delete()
        messages.success(request, "Bid berhasil dihapus.")
        return redirect("admin_dashboard:bid_list")
    return render(
        request,
        "admin_dashboard/confirm_delete.html",
        {"object": bid, "object_type": "bid", "cancel_url": "admin_dashboard:bid_list"},
    )

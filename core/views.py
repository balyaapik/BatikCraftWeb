"""Views that require an authenticated account.

Pages that anonymous visitors can open live in ``public_views`` and the
authentication flow lives in ``auth_views``.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import (
    AuctionInvoiceForm,
    BidForm,
    ModelAssetForm,
    NFTForm,
    PaymentSubmissionForm,
    ProfileForm,
)
from .models import (
    AuctionSettlement,
    Bid,
    ModelAsset,
    ModelPurchase,
    NFTAsset,
    User,
)


@login_required
def dashboard_router(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect("admin_dashboard:home")
    if request.user.role == User.Role.BUYER:
        return redirect("buyer_dashboard")
    return redirect("creator_dashboard")


@role_required(User.Role.CREATOR)
def creator_dashboard(request):
    nfts = request.user.nfts.annotate(
        bid_count=Count("bids"),
        max_bid=Max("bids__amount"),
    ).select_related("current_owner")
    models = request.user.model_listings.annotate(
        purchase_count=Count(
            "purchases",
            filter=Q(purchases__status=ModelPurchase.Status.PAID),
        )
    )
    settlements = request.user.auction_sales.select_related(
        "nft",
        "buyer",
        "winning_bid",
    )[:20]
    nft_totals = request.user.nfts.aggregate(
        total=Count("id", distinct=True),
        listed=Count(
            "id",
            filter=Q(status=NFTAsset.Status.LISTED),
            distinct=True,
        ),
        awaiting_payment=Count(
            "id",
            filter=Q(status=NFTAsset.Status.AWAITING_PAYMENT),
            distinct=True,
        ),
        sold=Count(
            "id",
            filter=Q(status=NFTAsset.Status.SOLD),
            distinct=True,
        ),
        total_bids=Count("bids", distinct=True),
    )
    model_totals = request.user.model_listings.aggregate(
        total=Count("id", distinct=True),
        sales=Count(
            "purchases",
            filter=Q(purchases__status=ModelPurchase.Status.PAID),
            distinct=True,
        ),
    )
    stats = {
        "total": nft_totals["total"],
        "listed": nft_totals["listed"],
        "awaiting_payment": nft_totals["awaiting_payment"],
        "sold": nft_totals["sold"],
        "total_bids": nft_totals["total_bids"],
        "models": model_totals["total"],
        "model_sales": model_totals["sales"],
    }
    return render(
        request,
        "core/creator_dashboard.html",
        {
            "nfts": nfts,
            "models": models,
            "settlements": settlements,
            "stats": stats,
        },
    )


@role_required(User.Role.BUYER)
def buyer_dashboard(request):
    now = timezone.now()
    market_items = (
        NFTAsset.objects.filter(status=NFTAsset.Status.LISTED)
        .filter(Q(auction_ends_at__isnull=True) | Q(auction_ends_at__gt=now))
        .select_related("owner")
        .annotate(bid_count=Count("bids"), max_bid=Max("bids__amount"))[:12]
    )
    own_bids = request.user.bids.select_related("nft", "nft__owner")[:10]
    auction_purchases = request.user.auction_purchases.select_related(
        "nft",
        "creator",
        "winning_bid",
    )[:20]
    owned_nfts = request.user.owned_nfts.filter(
        status=NFTAsset.Status.SOLD
    ).select_related("owner")
    model_library = request.user.model_purchases.filter(
        status=ModelPurchase.Status.PAID
    ).select_related("model", "model__seller")
    return render(
        request,
        "core/buyer_dashboard.html",
        {
            "market_items": market_items,
            "own_bids": own_bids,
            "auction_purchases": auction_purchases,
            "owned_nfts": owned_nfts,
            "model_library": model_library,
        },
    )


@login_required
def profile_edit(request):
    form = ProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=request.user,
    )
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
    return render(
        request,
        "core/nft_form.html",
        {"form": form, "title": "Tambah NFT"},
    )


@role_required(User.Role.CREATOR)
@require_POST
def nft_publish(request, pk):
    nft = get_object_or_404(NFTAsset, pk=pk, owner=request.user)
    if nft.starting_price <= Decimal("0"):
        messages.error(
            request,
            "Harga awal harus lebih dari nol sebelum NFT dipublikasikan.",
        )
    elif not nft.image and not nft.image_url:
        messages.error(
            request,
            "NFT harus memiliki gambar sebelum dipublikasikan.",
        )
    elif nft.status in {NFTAsset.Status.AWAITING_PAYMENT, NFTAsset.Status.SOLD}:
        messages.error(
            request,
            "NFT yang sedang ditagihkan atau sudah terjual tidak dapat dipublikasikan ulang.",
        )
    else:
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = timezone.now()
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        messages.success(request, "NFT berhasil ditayangkan di market.")
    return redirect("creator_dashboard")


@role_required(User.Role.BUYER)
@require_POST
def place_bid(request, pk):
    form = BidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Nominal bid tidak valid.")
        return redirect("nft_detail", pk=pk)
    with transaction.atomic():
        nft = get_object_or_404(
            NFTAsset.objects.select_for_update(),
            pk=pk,
        )
        if not nft.is_auction_open:
            messages.error(
                request,
                "Auction belum dibuka atau sudah berakhir.",
            )
            return redirect("nft_detail", pk=pk)
        if nft.owner_id == request.user.id:
            messages.error(
                request,
                "Pemilik NFT tidak dapat melakukan bid pada karyanya sendiri.",
            )
            return redirect("nft_detail", pk=pk)
        amount = form.cleaned_data["amount"]
        current = (
            nft.bids.aggregate(value=Max("amount"))["value"]
            or nft.starting_price
        )
        if amount <= current:
            messages.error(
                request,
                f"Bid harus lebih besar dari Rp{current:,.2f}.",
            )
            return redirect("nft_detail", pk=pk)
        Bid.objects.create(nft=nft, bidder=request.user, amount=amount)
    messages.success(request, "Bid berhasil dikirim.")
    return redirect("nft_detail", pk=pk)


def _settlement_queryset(lock=False):
    queryset = AuctionSettlement.objects.select_related(
        "nft",
        "nft__owner",
        "nft__current_owner",
        "winning_bid",
        "creator",
        "buyer",
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset


def _get_authorized_settlement(request, public_id, *, lock=False):
    settlement = get_object_or_404(
        _settlement_queryset(lock=lock),
        public_id=public_id,
    )
    if not (
        request.user.is_superuser
        or settlement.creator_id == request.user.id
        or settlement.buyer_id == request.user.id
    ):
        raise Http404("Invoice tidak ditemukan.")
    return settlement


def _expire_settlement(settlement):
    if not settlement.is_expired:
        return False
    settlement.status = AuctionSettlement.Status.EXPIRED
    settlement.save(update_fields=["status", "updated_at"])
    if settlement.nft.status == NFTAsset.Status.AWAITING_PAYMENT:
        settlement.nft.status = NFTAsset.Status.ARCHIVED
        settlement.nft.save(update_fields=["status", "updated_at"])
    return True


@role_required(User.Role.CREATOR)
@require_POST
def create_auction_invoice(request, pk):
    form = AuctionInvoiceForm(request.POST)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, " ".join(error))
        return redirect("nft_detail", pk=pk)

    with transaction.atomic():
        nft = get_object_or_404(
            NFTAsset.objects.select_for_update(),
            pk=pk,
            owner=request.user,
        )
        if hasattr(nft, "settlement"):
            messages.info(request, "Invoice untuk NFT ini sudah pernah dibuat.")
            return redirect(
                "settlement_detail",
                public_id=nft.settlement.public_id,
            )
        if not nft.auction_ends_at or timezone.now() < nft.auction_ends_at:
            messages.error(
                request,
                "Invoice hanya dapat dibuat setelah waktu auction selesai.",
            )
            return redirect("nft_detail", pk=pk)
        winning_bid = nft.bids.select_related("bidder").order_by(
            "-amount",
            "created_at",
        ).first()
        if winning_bid is None:
            messages.error(request, "Belum ada bid yang dapat ditagihkan.")
            return redirect("nft_detail", pk=pk)
        if nft.reserve_price is not None and winning_bid.amount < nft.reserve_price:
            messages.error(
                request,
                "Bid tertinggi belum mencapai harga minimum yang ditetapkan.",
            )
            return redirect("nft_detail", pk=pk)

        settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=winning_bid,
            creator=request.user,
            buyer=winning_bid.bidder,
            amount=winning_bid.amount,
            payment_method=form.cleaned_data["payment_method"],
            payment_instructions=form.cleaned_data["payment_instructions"],
            payment_due_at=timezone.now()
            + timedelta(hours=form.cleaned_data["payment_due_hours"]),
        )
        nft.status = NFTAsset.Status.AWAITING_PAYMENT
        nft.save(update_fields=["status", "updated_at"])

    messages.success(
        request,
        f"Invoice {settlement.invoice_number} dikirim kepada pemenang bid.",
    )
    return redirect("settlement_detail", public_id=settlement.public_id)


@login_required
def settlement_detail(request, public_id):
    settlement = _get_authorized_settlement(request, public_id)
    if _expire_settlement(settlement):
        messages.warning(request, "Invoice telah melewati batas pembayaran.")
    payment_form = PaymentSubmissionForm(instance=settlement)
    return render(
        request,
        "core/settlement_detail.html",
        {
            "settlement": settlement,
            "payment_form": payment_form,
        },
    )


@role_required(User.Role.BUYER)
@require_POST
def accept_auction_invoice(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(
            request,
            public_id,
            lock=True,
        )
        if settlement.buyer_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if _expire_settlement(settlement):
            messages.error(request, "Invoice sudah kedaluwarsa.")
        elif settlement.status != AuctionSettlement.Status.INVOICED:
            messages.info(request, "Invoice ini sudah diproses.")
        else:
            settlement.status = AuctionSettlement.Status.ACCEPTED
            settlement.accepted_at = timezone.now()
            settlement.review_note = ""
            settlement.save(
                update_fields=[
                    "status",
                    "accepted_at",
                    "review_note",
                    "updated_at",
                ]
            )
            messages.success(
                request,
                "Invoice disetujui. Silakan lakukan pembayaran.",
            )
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.BUYER)
@require_POST
def decline_auction_invoice(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(
            request,
            public_id,
            lock=True,
        )
        if settlement.buyer_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.INVOICED:
            messages.info(request, "Invoice ini sudah diproses.")
        else:
            settlement.status = AuctionSettlement.Status.DECLINED
            settlement.declined_at = timezone.now()
            settlement.buyer_note = request.POST.get("buyer_note", "").strip()
            settlement.save(
                update_fields=[
                    "status",
                    "declined_at",
                    "buyer_note",
                    "updated_at",
                ]
            )
            settlement.nft.status = NFTAsset.Status.ARCHIVED
            settlement.nft.save(update_fields=["status", "updated_at"])
            messages.info(request, "Invoice ditolak.")
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.BUYER)
@require_POST
def submit_auction_payment(request, public_id):
    settlement = _get_authorized_settlement(request, public_id)
    if settlement.buyer_id != request.user.id:
        raise Http404("Invoice tidak ditemukan.")
    form = PaymentSubmissionForm(
        request.POST,
        request.FILES,
        instance=settlement,
    )
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, " ".join(error))
        return redirect("settlement_detail", public_id=public_id)

    with transaction.atomic():
        locked = _get_authorized_settlement(request, public_id, lock=True)
        if _expire_settlement(locked):
            messages.error(request, "Invoice sudah kedaluwarsa.")
        elif locked.status != AuctionSettlement.Status.ACCEPTED:
            messages.error(
                request,
                "Pembayaran hanya dapat dikirim setelah invoice disetujui.",
            )
        else:
            locked.payment_reference = form.cleaned_data["payment_reference"]
            if form.cleaned_data.get("payment_proof"):
                locked.payment_proof = form.cleaned_data["payment_proof"]
            locked.buyer_note = form.cleaned_data["buyer_note"]
            locked.payment_submitted_at = timezone.now()
            locked.status = AuctionSettlement.Status.PAYMENT_SUBMITTED
            locked.review_note = ""
            locked.save(
                update_fields=[
                    "payment_reference",
                    "payment_proof",
                    "buyer_note",
                    "payment_submitted_at",
                    "status",
                    "review_note",
                    "updated_at",
                ]
            )
            messages.success(
                request,
                "Pembayaran dikirim untuk diverifikasi creator.",
            )
    return redirect("settlement_detail", public_id=public_id)


def _mint_paid_settlement(settlement):
    now = timezone.now()
    nft = settlement.nft
    if settlement.status == AuctionSettlement.Status.MINTED:
        return settlement

    nft.token_id = nft.token_id or f"BC-{uuid.uuid4().hex.upper()}"
    nft.blockchain = nft.blockchain or getattr(
        settings,
        "BATIKCRAFT_MINT_NETWORK",
        "BatikCraft Registry",
    )
    nft.contract_address = nft.contract_address or getattr(
        settings,
        "BATIKCRAFT_MINT_CONTRACT_ADDRESS",
        "",
    )
    nft.current_owner = settlement.buyer
    nft.minted_at = now
    nft.status = NFTAsset.Status.SOLD
    nft.save(
        update_fields=[
            "token_id",
            "blockchain",
            "contract_address",
            "current_owner",
            "minted_at",
            "status",
            "updated_at",
        ]
    )

    settlement.status = AuctionSettlement.Status.MINTED
    settlement.paid_at = now
    settlement.minted_at = now
    settlement.minted_to_wallet = settlement.buyer.wallet_address
    settlement.mint_reference = (
        settlement.mint_reference
        or f"BCMINT-{uuid.uuid4().hex[:20].upper()}"
    )
    settlement.review_note = ""
    settlement.save(
        update_fields=[
            "status",
            "paid_at",
            "minted_at",
            "minted_to_wallet",
            "mint_reference",
            "review_note",
            "updated_at",
        ]
    )
    return settlement


@role_required(User.Role.CREATOR)
@require_POST
def verify_auction_payment(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(
            request,
            public_id,
            lock=True,
        )
        if settlement.creator_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.PAYMENT_SUBMITTED:
            messages.error(
                request,
                "Belum ada pembayaran yang siap diverifikasi.",
            )
        else:
            _mint_paid_settlement(settlement)
            messages.success(
                request,
                "Pembayaran diverifikasi, NFT berhasil diterbitkan dan masuk ke akun buyer.",
            )
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.CREATOR)
@require_POST
def reject_auction_payment(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(
            request,
            public_id,
            lock=True,
        )
        if settlement.creator_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.PAYMENT_SUBMITTED:
            messages.error(
                request,
                "Tidak ada pembayaran yang sedang ditinjau.",
            )
        else:
            settlement.status = AuctionSettlement.Status.ACCEPTED
            settlement.review_note = (
                request.POST.get("review_note", "").strip()
                or "Bukti pembayaran belum dapat diverifikasi."
            )
            settlement.save(
                update_fields=["status", "review_note", "updated_at"]
            )
            messages.warning(
                request,
                "Pembayaran dikembalikan kepada buyer untuk diperbaiki.",
            )
    return redirect("settlement_detail", public_id=public_id)


@login_required
def settlement_payment_proof(request, public_id):
    settlement = _get_authorized_settlement(request, public_id)
    if not settlement.payment_proof:
        raise Http404("Bukti pembayaran tidak tersedia.")
    return FileResponse(
        settlement.payment_proof.open("rb"),
        as_attachment=False,
        filename=Path(settlement.payment_proof.name).name,
    )


@role_required(User.Role.CREATOR)
def model_create(request):
    form = ModelAssetForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        model = form.save(commit=False)
        model.seller = request.user
        model.save()
        messages.success(request, "Model disimpan sebagai draft.")
        return redirect("creator_dashboard")
    return render(
        request,
        "core/model_form.html",
        {"form": form, "title": "Jual Model BatikCraft"},
    )


@role_required(User.Role.CREATOR)
@require_POST
def model_publish(request, pk):
    model = get_object_or_404(ModelAsset, pk=pk, seller=request.user)
    if not model.model_file:
        messages.error(request, "Unggah file .batikmodel terlebih dahulu.")
    elif model.price < 0:
        messages.error(request, "Harga model tidak valid.")
    else:
        model.status = ModelAsset.Status.LISTED
        model.save(update_fields=["status", "updated_at"])
        messages.success(request, "Model berhasil ditayangkan di marketplace.")
    return redirect("creator_dashboard")


@login_required
@require_POST
def model_purchase(request, pk):
    model = get_object_or_404(
        ModelAsset,
        pk=pk,
        status=ModelAsset.Status.LISTED,
    )
    if model.seller_id == request.user.id:
        messages.info(request, "Model ini sudah menjadi milikmu.")
        return redirect("model_detail", pk=pk)
    with transaction.atomic():
        locked = ModelAsset.objects.select_for_update().get(pk=model.pk)
        _purchase, created = ModelPurchase.objects.get_or_create(
            model=locked,
            buyer=request.user,
            status=ModelPurchase.Status.PAID,
            defaults={
                "amount_paid": locked.price,
                "license_snapshot": {
                    "license_type": locked.license_type,
                    "commercial_use": locked.commercial_use,
                    "model_version": locked.version,
                },
            },
        )
    if created:
        messages.success(request, "Model masuk ke library akunmu.")
    else:
        messages.info(request, "Model sudah ada di library akunmu.")
    return redirect("model_detail", pk=pk)


@login_required
def model_download(request, pk):
    """Stream a purchased model file without exposing the storage URL."""

    model = get_object_or_404(ModelAsset, pk=pk)
    is_owner = model.seller_id == request.user.id or request.user.is_superuser
    purchase = None
    if not is_owner:
        purchase = get_object_or_404(
            ModelPurchase,
            model=model,
            buyer=request.user,
            status=ModelPurchase.Status.PAID,
        )
    if not model.model_file:
        raise Http404("File model tidak tersedia.")
    if purchase is not None:
        ModelPurchase.objects.filter(pk=purchase.pk).update(
            download_count=F("download_count") + 1
        )
    return FileResponse(
        model.model_file.open("rb"),
        as_attachment=True,
        filename=Path(model.model_file.name).name,
    )

"""Creator-facing auction lifecycle with fallback bidders and payout visibility."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from payments.services import (
    _schedule_payout,
    current_vat_percent,
    issue_listing_fee_invoice,
    listing_fee_is_paid,
)

from .decorators import role_required
from .forms import (
    AuctionInvoiceForm,
    AuctionRelistForm,
    NFTForm,
    PaymentSubmissionForm,
)
from .models import AuctionSettlement, Bid, NFTAsset, User, quantize_idr, quantize_money

_EXCLUDED_BIDDERS_KEY = "_auction_excluded_bidder_ids"
_TERMINAL_SETTLEMENT_STATUSES = {
    AuctionSettlement.Status.DECLINED,
    AuctionSettlement.Status.EXPIRED,
    AuctionSettlement.Status.CANCELLED,
}


def _settlement_queryset(*, lock: bool = False):
    queryset = AuctionSettlement.objects.select_related(
        "nft",
        "nft__owner",
        "nft__current_owner",
        "winning_bid",
        "creator",
        "buyer",
        "creator_payout",
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset


def _get_authorized_settlement(request, public_id, *, lock: bool = False):
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


def _excluded_bidder_ids(nft: NFTAsset) -> set[int]:
    values = (nft.metadata or {}).get(_EXCLUDED_BIDDERS_KEY, [])
    if not isinstance(values, list):
        return set()
    result = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _remember_excluded_bidder(nft: NFTAsset, bidder_id: int) -> None:
    metadata = dict(nft.metadata or {})
    values = _excluded_bidder_ids(nft)
    values.add(int(bidder_id))
    metadata[_EXCLUDED_BIDDERS_KEY] = sorted(values)
    nft.metadata = metadata
    nft.save(update_fields=["metadata", "updated_at"])


def _eligible_winning_bid(nft: NFTAsset, *, exclude_current: bool = False):
    excluded = _excluded_bidder_ids(nft)
    if exclude_current and hasattr(nft, "settlement"):
        excluded.add(nft.settlement.buyer_id)
    queryset = nft.bids.select_related("bidder")
    if excluded:
        queryset = queryset.exclude(bidder_id__in=excluded)
    winner = queryset.order_by("-amount", "created_at").first()
    if winner is None:
        return None
    if nft.reserve_price is not None and winner.amount < nft.reserve_price:
        return None
    return winner


def _expire_settlement(settlement: AuctionSettlement) -> bool:
    if not settlement.is_expired:
        return False
    settlement.status = AuctionSettlement.Status.EXPIRED
    settlement.review_note = (
        "Batas pembayaran terlewati. Creator dapat menawarkan kepada bidder berikutnya "
        "atau membuka kembali lelang."
    )
    settlement.save(update_fields=["status", "review_note", "updated_at"])
    _remember_excluded_bidder(settlement.nft, settlement.buyer_id)
    return True


def _clear_payment_data(settlement: AuctionSettlement) -> None:
    if settlement.payment_proof:
        settlement.payment_proof.delete(save=False)
    settlement.payment_reference = ""
    settlement.payment_proof = None
    settlement.buyer_note = ""
    settlement.review_note = ""
    settlement.accepted_at = None
    settlement.payment_submitted_at = None
    settlement.paid_at = None
    settlement.minted_at = None
    settlement.minted_to_wallet = ""
    settlement.mint_reference = None
    settlement.declined_at = None
    settlement.cancelled_at = None


def _configure_invoice(
    settlement: AuctionSettlement,
    *,
    winning_bid: Bid,
    payment_method: str,
    payment_instructions: str,
    payment_due_hours: int,
) -> AuctionSettlement:
    vat_percent = current_vat_percent()
    vat_amount = quantize_idr(
        winning_bid.amount * (vat_percent / Decimal(100))
    )
    _clear_payment_data(settlement)
    settlement.winning_bid = winning_bid
    settlement.buyer = winning_bid.bidder
    settlement.subtotal_amount = winning_bid.amount
    settlement.vat_percent = vat_percent
    settlement.vat_amount = vat_amount
    settlement.amount = winning_bid.amount + vat_amount
    settlement.payment_method = payment_method
    settlement.payment_instructions = payment_instructions
    settlement.payment_due_at = timezone.now() + timedelta(hours=payment_due_hours)
    settlement.status = AuctionSettlement.Status.INVOICED
    settlement.save()
    settlement.nft.status = NFTAsset.Status.AWAITING_PAYMENT
    settlement.nft.save(update_fields=["status", "updated_at"])
    return settlement


@role_required(User.Role.CREATOR)
def nft_edit(request, pk):
    nft = get_object_or_404(NFTAsset, pk=pk, owner=request.user)
    if nft.status != NFTAsset.Status.DRAFT:
        messages.error(
            request,
            "Metadata hanya dapat diubah ketika listing masih berupa draft.",
        )
        return redirect("nft_detail", pk=nft.pk)
    form = NFTForm(request.POST or None, instance=nft)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Metadata dan aturan lelang berhasil diperbarui.")
        return redirect("creator_dashboard")
    return render(
        request,
        "core/nft_form.html",
        {"form": form, "title": "Edit metadata dan aturan lelang"},
    )


@role_required(User.Role.CREATOR)
@require_POST
def nft_publish(request, pk):
    nft = get_object_or_404(NFTAsset, pk=pk, owner=request.user)
    now = timezone.now()
    if nft.starting_price <= Decimal(0):
        messages.error(request, "Harga awal harus lebih dari nol sebelum dipublikasikan.")
    elif not nft.auction_ends_at:
        messages.error(request, "Batas akhir lelang wajib diisi sebelum dipublikasikan.")
    elif nft.auction_ends_at <= now:
        messages.error(request, "Batas akhir lelang harus berada di masa depan.")
    elif nft.reserve_price is not None and nft.reserve_price < nft.starting_price:
        messages.error(request, "Reserve price tidak boleh lebih rendah dari harga awal.")
    elif not nft.image and not nft.image_url:
        messages.error(request, "NFT harus memiliki gambar dari paket Studio.")
    elif nft.status in {NFTAsset.Status.AWAITING_PAYMENT, NFTAsset.Status.SOLD}:
        messages.error(
            request,
            "NFT yang sedang ditagihkan atau sudah terjual tidak dapat dipublikasikan ulang.",
        )
    elif not listing_fee_is_paid(nft):
        fee_invoice = issue_listing_fee_invoice(nft)
        messages.error(
            request,
            (
                f"Fee bidding Rp{fee_invoice.total_amount:,.0f} harus dilunasi "
                "sebelum NFT tayang. Gunakan tombol Bayar fee."
            ),
        )
    else:
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at or nft.auction_starts_at < now:
            nft.auction_starts_at = now
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
        messages.success(request, "NFT berhasil ditayangkan di market.")
    return redirect("creator_dashboard")


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
        if not nft.auction_ends_at or timezone.now() < nft.auction_ends_at:
            messages.error(request, "Invoice hanya dapat dibuat setelah auction selesai.")
            return redirect("nft_detail", pk=pk)
        winning_bid = _eligible_winning_bid(nft)
        if winning_bid is None:
            messages.error(
                request,
                "Tidak ada bid yang memenuhi reserve price dan dapat ditagihkan.",
            )
            return redirect("nft_detail", pk=pk)

        settlement = getattr(nft, "settlement", None)
        if settlement is not None and settlement.status not in _TERMINAL_SETTLEMENT_STATUSES:
            messages.info(request, "Invoice aktif untuk NFT ini sudah tersedia.")
            return redirect("settlement_detail", public_id=settlement.public_id)
        if settlement is None:
            settlement = AuctionSettlement(
                nft=nft,
                creator=request.user,
                winning_bid=winning_bid,
                buyer=winning_bid.bidder,
                subtotal_amount=winning_bid.amount,
                amount=winning_bid.amount,
                payment_instructions="",
                payment_due_at=timezone.now(),
            )
        _configure_invoice(
            settlement,
            winning_bid=winning_bid,
            payment_method=form.cleaned_data["payment_method"],
            payment_instructions=form.cleaned_data["payment_instructions"],
            payment_due_hours=form.cleaned_data["payment_due_hours"],
        )

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
    relist_form = AuctionRelistForm(
        initial={"reserve_price": settlement.nft.reserve_price}
    )
    next_bid = None
    if settlement.status in _TERMINAL_SETTLEMENT_STATUSES:
        next_bid = _eligible_winning_bid(settlement.nft, exclude_current=True)
    return render(
        request,
        "core/settlement_detail.html",
        {
            "settlement": settlement,
            "payment_form": payment_form,
            "relist_form": relist_form,
            "next_bid": next_bid,
        },
    )


@role_required(User.Role.BUYER)
@require_POST
def accept_auction_invoice(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(request, public_id, lock=True)
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
                update_fields=["status", "accepted_at", "review_note", "updated_at"]
            )
            messages.success(request, "Invoice disetujui. Silakan lakukan pembayaran.")
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.BUYER)
@require_POST
def decline_auction_invoice(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(request, public_id, lock=True)
        if settlement.buyer_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.INVOICED:
            messages.info(request, "Invoice ini sudah diproses.")
        else:
            settlement.status = AuctionSettlement.Status.DECLINED
            settlement.declined_at = timezone.now()
            settlement.buyer_note = request.POST.get("buyer_note", "").strip()
            settlement.review_note = (
                "Buyer menolak invoice. Creator dapat menawarkan kepada bidder berikutnya "
                "atau membuka kembali lelang."
            )
            settlement.save(
                update_fields=[
                    "status",
                    "declined_at",
                    "buyer_note",
                    "review_note",
                    "updated_at",
                ]
            )
            _remember_excluded_bidder(settlement.nft, settlement.buyer_id)
            messages.info(request, "Invoice ditolak dan creator telah diberi opsi lanjutan.")
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
            messages.error(request, "Pembayaran hanya dapat dikirim setelah invoice disetujui.")
        else:
            locked.payment_reference = form.cleaned_data["payment_reference"]
            if form.cleaned_data.get("payment_proof"):
                locked.payment_proof = form.cleaned_data["payment_proof"]
            locked.buyer_note = form.cleaned_data["buyer_note"]
            locked.payment_submitted_at = timezone.now()
            locked.status = AuctionSettlement.Status.PAYMENT_SUBMITTED
            locked.review_note = ""
            locked.save()
            messages.success(request, "Pembayaran dikirim untuk diverifikasi creator.")
    return redirect("settlement_detail", public_id=public_id)


def _mint_paid_settlement(settlement: AuctionSettlement):
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
    nft.save()

    settlement.status = AuctionSettlement.Status.MINTED
    settlement.paid_at = now
    settlement.minted_at = now
    settlement.minted_to_wallet = settlement.buyer.wallet_address
    settlement.mint_reference = settlement.mint_reference or (
        f"BCMINT-{uuid.uuid4().hex[:20].upper()}"
    )
    settlement.review_note = ""
    settlement.save()
    _schedule_payout(settlement.pk)
    return settlement


@role_required(User.Role.CREATOR)
@require_POST
def verify_auction_payment(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(request, public_id, lock=True)
        if settlement.creator_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.PAYMENT_SUBMITTED:
            messages.error(request, "Belum ada pembayaran yang siap diverifikasi.")
        else:
            _mint_paid_settlement(settlement)
            messages.success(
                request,
                "Pembayaran diverifikasi, NFT diterbitkan, dan payout creator disiapkan.",
            )
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.CREATOR)
@require_POST
def reject_auction_payment(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(request, public_id, lock=True)
        if settlement.creator_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status != AuctionSettlement.Status.PAYMENT_SUBMITTED:
            messages.error(request, "Tidak ada pembayaran yang sedang ditinjau.")
        else:
            settlement.status = AuctionSettlement.Status.ACCEPTED
            settlement.review_note = (
                request.POST.get("review_note", "").strip()
                or "Bukti pembayaran belum dapat diverifikasi."
            )
            settlement.save(update_fields=["status", "review_note", "updated_at"])
            messages.warning(request, "Pembayaran dikembalikan untuk diperbaiki buyer.")
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.CREATOR)
@require_POST
def offer_next_bidder(request, public_id):
    with transaction.atomic():
        settlement = _get_authorized_settlement(request, public_id, lock=True)
        if settlement.creator_id != request.user.id:
            raise Http404("Invoice tidak ditemukan.")
        if settlement.status not in _TERMINAL_SETTLEMENT_STATUSES:
            messages.error(request, "Bidder berikutnya hanya dapat dipilih dari invoice gagal.")
            return redirect("settlement_detail", public_id=public_id)
        _remember_excluded_bidder(settlement.nft, settlement.buyer_id)
        next_bid = _eligible_winning_bid(settlement.nft, exclude_current=True)
        if next_bid is None:
            messages.error(request, "Tidak ada bidder berikutnya yang memenuhi reserve price.")
            return redirect("settlement_detail", public_id=public_id)
        _configure_invoice(
            settlement,
            winning_bid=next_bid,
            payment_method=settlement.payment_method,
            payment_instructions=settlement.payment_instructions,
            payment_due_hours=48,
        )
        messages.success(
            request,
            f"Invoice diteruskan kepada {next_bid.bidder.public_name}.",
        )
    return redirect("settlement_detail", public_id=public_id)


@role_required(User.Role.CREATOR)
@require_POST
def reopen_auction(request, public_id):
    form = AuctionRelistForm(request.POST)
    settlement = _get_authorized_settlement(request, public_id)
    if settlement.creator_id != request.user.id:
        raise Http404("Invoice tidak ditemukan.")
    if settlement.status not in _TERMINAL_SETTLEMENT_STATUSES:
        messages.error(request, "Lelang hanya dapat dibuka kembali setelah invoice gagal.")
        return redirect("settlement_detail", public_id=public_id)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, " ".join(error))
        return redirect("settlement_detail", public_id=public_id)

    with transaction.atomic():
        locked = _get_authorized_settlement(request, public_id, lock=True)
        nft = NFTAsset.objects.select_for_update().get(pk=locked.nft_id)
        nft.status = NFTAsset.Status.LISTED
        nft.auction_starts_at = timezone.now()
        nft.auction_ends_at = form.cleaned_data["auction_ends_at"]
        nft.reserve_price = form.cleaned_data["reserve_price"]
        nft.save(
            update_fields=[
                "status",
                "auction_starts_at",
                "auction_ends_at",
                "reserve_price",
                "updated_at",
            ]
        )
        locked.status = AuctionSettlement.Status.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.review_note = (
            "Lelang dibuka kembali. Bidder yang sebelumnya menolak atau kedaluwarsa "
            "tetap dikecualikan dari pemenang berikutnya."
        )
        locked.save(update_fields=["status", "cancelled_at", "review_note", "updated_at"])
    messages.success(request, "Lelang berhasil dibuka kembali.")
    return redirect("nft_detail", pk=settlement.nft_id)


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

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import AuctionSettlement, NFTAsset

from .models import (
    CreatorPayout,
    ListingFeeInvoice,
    PaymentGatewayAttempt,
    PaymentGatewayEvent,
    PlatformFeeSetting,
)
from .xendit import (
    XenditError,
    classify_status,
    create_payout,
    invoice_data,
    settlement_payment_method,
)

logger = logging.getLogger(__name__)


def current_vat_percent():
    """Tarif PPN yang berlaku saat ini (default 11%)."""
    return PlatformFeeSetting.load().vat_percent


def listing_fee_is_paid(nft) -> bool:
    """True bila fee bidding untuk NFT ini sudah lunas."""
    return ListingFeeInvoice.objects.filter(
        nft=nft,
        status=ListingFeeInvoice.Status.PAID,
    ).exists()


def listing_fee_quote(nft) -> dict:
    """Rincian fee yang akan ditagihkan tanpa menerbitkan invoice."""
    return PlatformFeeSetting.load().quote_listing_fee(nft.starting_price)


@transaction.atomic
def issue_listing_fee_invoice(nft) -> ListingFeeInvoice:
    """Terbitkan (atau ambil kembali) tagihan fee bidding untuk sebuah NFT.

    Fee dihitung dari harga terendah yang dicantumkan creator. Tagihan yang
    sudah lunas tidak pernah dibuat ulang, sehingga creator tidak tertagih dua
    kali untuk listing yang sama.
    """
    existing = ListingFeeInvoice.objects.select_for_update().filter(nft=nft).first()
    if existing and existing.status == ListingFeeInvoice.Status.PAID:
        return existing

    config = PlatformFeeSetting.load()
    quote = config.quote_listing_fee(nft.starting_price)
    due_at = timezone.now() + timedelta(hours=config.listing_fee_due_hours)

    if existing:
        # Tagihan belum lunas: perbarui mengikuti harga dan tarif terkini.
        has_active_attempt = existing.gateway_attempts.filter(
            status__in=[
                PaymentGatewayAttempt.Status.CREATED,
                PaymentGatewayAttempt.Status.PENDING,
            ]
        ).exists()
        if has_active_attempt:
            return existing
        for field, value in quote.items():
            setattr(existing, field, value)
        existing.status = ListingFeeInvoice.Status.PENDING
        existing.due_at = due_at
        existing.full_clean(exclude=["invoice_number"])
        existing.save()
        return existing

    invoice = ListingFeeInvoice(
        nft=nft,
        creator=nft.owner,
        due_at=due_at,
        **quote,
    )
    invoice.full_clean(exclude=["invoice_number"])
    invoice.save()
    return invoice


@transaction.atomic
def mark_listing_fee_paid(fee_invoice_id: int, attempt_id: int) -> ListingFeeInvoice:
    """Tandai fee lunas dan tayangkan listing NFT-nya."""
    fee_invoice = (
        ListingFeeInvoice.objects.select_for_update()
        .select_related("nft")
        .get(pk=fee_invoice_id)
    )
    attempt = PaymentGatewayAttempt.objects.select_for_update().get(pk=attempt_id)

    if fee_invoice.status == ListingFeeInvoice.Status.PAID:
        return fee_invoice
    if attempt.status != PaymentGatewayAttempt.Status.PAID:
        raise ValidationError("Gateway belum menyatakan fee lunas.")
    if attempt.amount != fee_invoice.total_amount:
        raise ValidationError("Nominal gateway berbeda dari total fee.")

    now = attempt.paid_at or timezone.now()
    fee_invoice.status = ListingFeeInvoice.Status.PAID
    fee_invoice.paid_at = now
    fee_invoice.payment_reference = attempt.transaction_id or attempt.order_id
    fee_invoice.save(
        update_fields=["status", "paid_at", "payment_reference", "updated_at"]
    )

    nft = NFTAsset.objects.select_for_update().get(pk=fee_invoice.nft_id)
    if nft.status == NFTAsset.Status.DRAFT:
        nft.status = NFTAsset.Status.LISTED
        if not nft.auction_starts_at:
            nft.auction_starts_at = now
        nft.save(update_fields=["status", "auction_starts_at", "updated_at"])
    return fee_invoice


@transaction.atomic
def create_creator_payout(settlement_id: int) -> CreatorPayout | None:
    """Siapkan payout untuk creator setelah invoice buyer lunas.

    Creator menerima nilai bid penuh: fee sudah dibayar di muka dan PPN 11%
    yang ditagihkan ke buyer disetorkan oleh platform, bukan hak creator.
    """
    settlement = (
        AuctionSettlement.objects.select_for_update()
        .select_related("creator")
        .get(pk=settlement_id)
    )
    if settlement.status != AuctionSettlement.Status.MINTED:
        raise ValidationError("Payout hanya dibuat setelah invoice lunas.")

    existing = CreatorPayout.objects.filter(settlement=settlement).first()
    if existing:
        return existing

    creator = settlement.creator
    payout = CreatorPayout.objects.create(
        settlement=settlement,
        creator=creator,
        amount=settlement.subtotal_amount or settlement.amount,
        bank_name=creator.payout_bank_code,
        account_number=creator.payout_account_number,
        account_holder=creator.payout_account_holder,
        reference_id=f"BCPO-{uuid.uuid4().hex[:20].upper()}",
    )
    return payout


@transaction.atomic
def dispatch_creator_payout(payout_id: int) -> CreatorPayout:
    """Kirim payout ke Xendit. Aman dipanggil ulang untuk payout yang gagal."""
    payout = (
        CreatorPayout.objects.select_for_update()
        .select_related("creator", "settlement")
        .get(pk=payout_id)
    )
    if payout.status in {CreatorPayout.Status.SUCCESS, CreatorPayout.Status.PROCESSING}:
        return payout

    try:
        response = create_payout(payout)
    except XenditError as exc:
        payout.status = CreatorPayout.Status.FAILED
        payout.failure_reason = str(exc)[:255]
        payout.response_payload = {"error": str(exc)}
        payout.save(
            update_fields=[
                "status",
                "failure_reason",
                "response_payload",
                "updated_at",
            ]
        )
        logger.warning("Payout %s gagal dikirim: %s", payout.reference_id, exc)
        return payout

    payout.status = CreatorPayout.Status.PROCESSING
    payout.payout_reference = str(response.get("id", ""))[:120]
    payout.response_payload = response
    payout.failure_reason = ""
    payout.save(
        update_fields=[
            "status",
            "payout_reference",
            "response_payload",
            "failure_reason",
            "updated_at",
        ]
    )
    return payout


@transaction.atomic
def mint_verified_settlement(settlement_id: int, attempt_id: int):
    settlement = (
        AuctionSettlement.objects.select_for_update()
        .select_related("buyer")
        .get(pk=settlement_id)
    )
    attempt = PaymentGatewayAttempt.objects.select_for_update().get(pk=attempt_id)
    nft = NFTAsset.objects.select_for_update().get(pk=settlement.nft_id)

    if settlement.status == AuctionSettlement.Status.MINTED:
        return settlement
    if attempt.status != PaymentGatewayAttempt.Status.PAID:
        raise ValidationError("Gateway belum menyatakan pembayaran lunas.")
    if attempt.amount != settlement.amount:
        raise ValidationError("Nominal gateway berbeda dari nilai invoice.")

    now = attempt.paid_at or timezone.now()
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
    settlement.payment_method = settlement_payment_method(attempt.payment_type)
    settlement.payment_reference = attempt.transaction_id or attempt.order_id
    settlement.payment_submitted_at = settlement.payment_submitted_at or now
    settlement.paid_at = now
    settlement.minted_at = now
    settlement.minted_to_wallet = settlement.buyer.wallet_address
    settlement.mint_reference = (
        settlement.mint_reference
        or f"BCMINT-{uuid.uuid4().hex[:20].upper()}"
    )
    settlement.review_note = "Pembayaran diverifikasi otomatis oleh Xendit."
    settlement.save(
        update_fields=[
            "status",
            "payment_method",
            "payment_reference",
            "payment_submitted_at",
            "paid_at",
            "minted_at",
            "minted_to_wallet",
            "mint_reference",
            "review_note",
            "updated_at",
        ]
    )
    return settlement


@transaction.atomic
def apply_verified_xendit_status(
    attempt_id: int,
    payload: dict,
    event_key: str,
    *,
    signature_valid: bool,
):
    attempt = (
        PaymentGatewayAttempt.objects.select_for_update()
        .select_related("settlement", "listing_fee")
        .get(pk=attempt_id)
    )
    invoice = invoice_data(payload)
    event, created = PaymentGatewayEvent.objects.get_or_create(
        event_key=event_key,
        defaults={
            "attempt": attempt,
            "transaction_status": str(invoice.get("status", "")),
            "payload": payload,
            "signature_valid": signature_valid,
            "verified_with_api": True,
        },
    )
    if not created and event.processed:
        return attempt, event, False

    classification = classify_status(payload)
    status_map = {
        "paid": PaymentGatewayAttempt.Status.PAID,
        "pending": PaymentGatewayAttempt.Status.PENDING,
        "failed": PaymentGatewayAttempt.Status.FAILED,
        "expired": PaymentGatewayAttempt.Status.EXPIRED,
        "cancelled": PaymentGatewayAttempt.Status.CANCELLED,
        "refunded": PaymentGatewayAttempt.Status.REFUNDED,
    }
    attempt.status = status_map[classification]
    attempt.gateway_status = str(invoice.get("status", ""))[:32]
    attempt.transaction_id = str(
        invoice.get("payment_id") or invoice.get("id") or ""
    )[:120]
    attempt.payment_type = str(
        invoice.get("payment_method") or invoice.get("payment_channel") or "QRIS"
    )[:64]
    attempt.gateway_response = payload
    update_fields = [
        "status",
        "gateway_status",
        "transaction_id",
        "payment_type",
        "gateway_response",
        "updated_at",
    ]
    if classification == "paid" and not attempt.paid_at:
        attempt.paid_at = timezone.now()
        update_fields.append("paid_at")
    attempt.save(update_fields=update_fields)

    if attempt.purpose == PaymentGatewayAttempt.Purpose.LISTING_FEE:
        outcome = _apply_listing_fee_outcome(attempt, classification)
    elif classification == "paid":
        mint_verified_settlement(attempt.settlement_id, attempt.id)
        outcome = "paid-and-minted"
        _schedule_payout(attempt.settlement_id)
    elif classification == "refunded":
        settlement = AuctionSettlement.objects.select_for_update().get(
            pk=attempt.settlement_id
        )
        settlement.review_note = (
            "Gateway melaporkan refund/chargeback. Administrator harus meninjau "
            "kepemilikan NFT dan penyelesaian dana secara manual."
        )
        settlement.save(update_fields=["review_note", "updated_at"])
        outcome = "refund-review-required"
    else:
        outcome = classification

    event.transaction_status = str(invoice.get("status", ""))[:32]
    event.payload = payload
    event.signature_valid = signature_valid
    event.verified_with_api = True
    event.processed = True
    event.outcome = outcome
    event.save(
        update_fields=[
            "transaction_status",
            "payload",
            "signature_valid",
            "verified_with_api",
            "processed",
            "outcome",
        ]
    )
    return attempt, event, True


def _apply_listing_fee_outcome(attempt, classification: str) -> str:
    """Terjemahkan status gateway menjadi status tagihan fee listing."""
    if classification == "paid":
        mark_listing_fee_paid(attempt.listing_fee_id, attempt.id)
        return "listing-fee-paid"
    if classification in {"expired", "cancelled"}:
        target = (
            ListingFeeInvoice.Status.EXPIRED
            if classification == "expired"
            else ListingFeeInvoice.Status.CANCELLED
        )
        ListingFeeInvoice.objects.filter(
            pk=attempt.listing_fee_id,
            status=ListingFeeInvoice.Status.PENDING,
        ).update(status=target, updated_at=timezone.now())
        return f"listing-fee-{classification}"
    return f"listing-fee-{classification}"


def _schedule_payout(settlement_id: int) -> None:
    """Buat payout creator, lalu kirim bila payout otomatis diaktifkan.

    Kegagalan payout tidak boleh membatalkan transaksi pembayaran buyer yang
    sudah sah, jadi seluruh error dicatat dan payout tetap tersimpan untuk
    diproses ulang oleh administrator.
    """
    try:
        payout = create_creator_payout(settlement_id)
    except (ValidationError, CreatorPayout.DoesNotExist) as exc:
        logger.warning("Payout untuk settlement %s gagal disiapkan: %s", settlement_id, exc)
        return
    if payout is None:
        return
    if not PlatformFeeSetting.load().auto_payout_enabled:
        return
    if not payout.creator.has_payout_account:
        CreatorPayout.objects.filter(pk=payout.pk).update(
            status=CreatorPayout.Status.FAILED,
            failure_reason="Creator belum melengkapi rekening tujuan payout.",
        )
        return
    transaction.on_commit(lambda: dispatch_creator_payout(payout.pk))

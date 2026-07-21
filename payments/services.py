from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import AuctionSettlement, NFTAsset

from .midtrans import classify_status, settlement_payment_method
from .models import PaymentGatewayAttempt, PaymentGatewayEvent


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
    settlement.review_note = "Pembayaran diverifikasi otomatis oleh Midtrans."
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
def apply_verified_midtrans_status(
    attempt_id: int,
    payload: dict,
    event_key: str,
    *,
    signature_valid: bool,
):
    attempt = (
        PaymentGatewayAttempt.objects.select_for_update()
        .select_related("settlement")
        .get(pk=attempt_id)
    )
    event, created = PaymentGatewayEvent.objects.get_or_create(
        event_key=event_key,
        defaults={
            "attempt": attempt,
            "transaction_status": str(payload.get("transaction_status", "")),
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
    attempt.gateway_status = str(payload.get("transaction_status", ""))[:32]
    attempt.transaction_id = str(payload.get("transaction_id", ""))[:120]
    attempt.payment_type = str(payload.get("payment_type", ""))[:64]
    attempt.fraud_status = str(payload.get("fraud_status", ""))[:32]
    attempt.gateway_response = payload
    update_fields = [
        "status",
        "gateway_status",
        "transaction_id",
        "payment_type",
        "fraud_status",
        "gateway_response",
        "updated_at",
    ]
    if classification == "paid" and not attempt.paid_at:
        attempt.paid_at = timezone.now()
        update_fields.append("paid_at")
    attempt.save(update_fields=update_fields)

    if classification == "paid":
        mint_verified_settlement(attempt.settlement_id, attempt.id)
        outcome = "paid-and-minted"
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

    event.transaction_status = str(payload.get("transaction_status", ""))[:32]
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

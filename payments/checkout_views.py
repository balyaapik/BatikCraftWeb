from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import AuctionSettlement, NFTAsset

from .models import ListingFeeInvoice, PaymentGatewayAttempt
from .services import apply_verified_xendit_status, issue_listing_fee_invoice
from .views import _authorized_settlement, _resolve_fee_invoice, _validate_verified_invoice
from .xendit import (
    XenditError,
    create_invoice,
    environment_name,
    get_invoice,
    is_enabled,
    verified_event_key,
)

logger = logging.getLogger(__name__)
_STALE_CREATED_AFTER = timedelta(minutes=2)


def _active_attempt(billable):
    now = timezone.now()
    return (
        billable.gateway_attempts.filter(
            status__in=[
                PaymentGatewayAttempt.Status.CREATED,
                PaymentGatewayAttempt.Status.PENDING,
            ]
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .first()
    )


def _latest_verifiable_attempt(billable):
    return billable.gateway_attempts.exclude(invoice_id="").first()


def _retire_stale_created_attempt(attempt) -> bool:
    if (
        attempt is None
        or attempt.status != PaymentGatewayAttempt.Status.CREATED
        or attempt.invoice_url
        or attempt.created_at > timezone.now() - _STALE_CREATED_AFTER
    ):
        return False
    response = dict(attempt.gateway_response or {})
    response["error"] = "stale-checkout-attempt"
    response["detail"] = (
        "Percobaan checkout tidak selesai dibuat dan telah dibuka untuk dicoba ulang."
    )
    attempt.status = PaymentGatewayAttempt.Status.FAILED
    attempt.expires_at = timezone.now()
    attempt.gateway_response = response
    attempt.save(
        update_fields=["status", "expires_at", "gateway_response", "updated_at"]
    )
    return True


@login_required
@require_POST
def start_xendit_checkout(request, public_id):
    if not is_enabled():
        messages.error(
            request,
            "Xendit belum dikonfigurasi oleh administrator. Gunakan pembayaran manual.",
        )
        return redirect("settlement_detail", public_id=public_id)

    with transaction.atomic():
        settlement = _authorized_settlement(request, public_id, lock=True)
        if settlement.buyer_id != request.user.id:
            from django.http import Http404

            raise Http404("Invoice tidak ditemukan.")
        if settlement.status == AuctionSettlement.Status.MINTED:
            messages.info(request, "Invoice ini sudah lunas.")
            return redirect("settlement_detail", public_id=public_id)
        if settlement.status != AuctionSettlement.Status.ACCEPTED:
            messages.error(
                request,
                "Setujui invoice sebelum membuka checkout otomatis.",
            )
            return redirect("settlement_detail", public_id=public_id)
        if timezone.now() >= settlement.payment_due_at:
            messages.error(request, "Invoice sudah kedaluwarsa.")
            return redirect("settlement_detail", public_id=public_id)

        existing = _active_attempt(settlement)
        if _retire_stale_created_attempt(existing):
            existing = None
        if existing:
            if existing.invoice_url:
                return HttpResponseRedirect(existing.invoice_url)
            messages.info(request, "Checkout sedang dibuat. Silakan coba kembali sebentar lagi.")
            return redirect("settlement_detail", public_id=public_id)

        expiry = min(settlement.payment_due_at, timezone.now() + timedelta(days=7))
        order_id = f"BCPAY-{settlement.public_id.hex[:20]}-{uuid.uuid4().hex[:8]}"
        attempt = PaymentGatewayAttempt.objects.create(
            settlement=settlement,
            provider=PaymentGatewayAttempt.Provider.XENDIT,
            environment=environment_name(),
            order_id=order_id,
            amount=settlement.amount,
            expires_at=expiry,
        )

    finish_url = request.build_absolute_uri(
        reverse("settlement_detail", args=[settlement.public_id])
    )
    try:
        response = create_invoice(attempt, finish_url)
    except XenditError as exc:
        PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentGatewayAttempt.Status.FAILED,
            gateway_response={"error": str(exc)},
        )
        logger.warning("Xendit checkout failed for %s: %s", order_id, exc)
        messages.error(request, f"Checkout gagal dibuat: {exc}")
        return redirect("settlement_detail", public_id=public_id)

    PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
        status=PaymentGatewayAttempt.Status.PENDING,
        invoice_id=str(response["id"]),
        invoice_url=str(response["invoice_url"]),
        gateway_response=response,
    )
    return HttpResponseRedirect(str(response["invoice_url"]))


@login_required
@require_POST
def start_listing_fee_checkout(request, pk):
    if not is_enabled():
        messages.error(request, "Xendit belum dikonfigurasi oleh administrator.")
        return redirect("creator_dashboard")

    with transaction.atomic():
        nft = _resolve_fee_invoice(request, pk)
        if nft.starting_price <= 0:
            messages.error(
                request,
                "Tetapkan harga awal sebelum membayar fee bidding.",
            )
            return redirect("creator_dashboard")
        if nft.status in {NFTAsset.Status.AWAITING_PAYMENT, NFTAsset.Status.SOLD}:
            messages.error(
                request,
                "NFT yang sedang ditagihkan atau sudah terjual tidak perlu fee baru.",
            )
            return redirect("creator_dashboard")

        fee_invoice = issue_listing_fee_invoice(nft)
        if fee_invoice.status == ListingFeeInvoice.Status.PAID:
            messages.info(request, "Fee bidding untuk NFT ini sudah lunas.")
            return redirect("creator_dashboard")

        existing = _active_attempt(fee_invoice)
        if _retire_stale_created_attempt(existing):
            existing = None
        if existing:
            if existing.invoice_url:
                return HttpResponseRedirect(existing.invoice_url)
            messages.info(request, "Checkout sedang dibuat. Silakan coba kembali sebentar lagi.")
            return redirect("creator_dashboard")

        expiry = min(fee_invoice.due_at, timezone.now() + timedelta(days=7))
        order_id = f"BCFEE-{fee_invoice.public_id.hex[:20]}-{uuid.uuid4().hex[:8]}"
        attempt = PaymentGatewayAttempt.objects.create(
            purpose=PaymentGatewayAttempt.Purpose.LISTING_FEE,
            listing_fee=fee_invoice,
            provider=PaymentGatewayAttempt.Provider.XENDIT,
            environment=environment_name(),
            order_id=order_id,
            amount=fee_invoice.total_amount,
            expires_at=expiry,
        )

    finish_url = request.build_absolute_uri(reverse("creator_dashboard"))
    try:
        response = create_invoice(attempt, finish_url)
    except XenditError as exc:
        PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentGatewayAttempt.Status.FAILED,
            gateway_response={"error": str(exc)},
        )
        logger.warning("Xendit listing fee checkout failed for %s: %s", order_id, exc)
        messages.error(request, f"Checkout fee gagal dibuat: {exc}")
        return redirect("creator_dashboard")

    PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
        status=PaymentGatewayAttempt.Status.PENDING,
        invoice_id=str(response["id"]),
        invoice_url=str(response["invoice_url"]),
        gateway_response=response,
    )
    return HttpResponseRedirect(str(response["invoice_url"]))


@login_required
@require_GET
def settlement_gateway_status(request, public_id):
    settlement = _authorized_settlement(request, public_id)
    attempt = _latest_verifiable_attempt(settlement) or settlement.gateway_attempts.first()
    return JsonResponse(
        {
            "settlement_status": settlement.status,
            "settlement_complete": settlement.status
            == AuctionSettlement.Status.MINTED,
            "attempt": (
                {
                    "status": attempt.status,
                    "gateway_status": attempt.gateway_status,
                    "payment_type": attempt.payment_type,
                    "transaction_id": attempt.transaction_id,
                    "invoice_url": attempt.invoice_url,
                    "paid_at": attempt.paid_at.isoformat() if attempt.paid_at else None,
                }
                if attempt
                else None
            ),
        }
    )


@login_required
@require_POST
def sync_xendit_status(request, public_id):
    settlement = _authorized_settlement(request, public_id)
    attempt = _latest_verifiable_attempt(settlement)
    if not attempt:
        messages.error(request, "Belum ada invoice Xendit yang dapat disinkronkan.")
        return redirect("settlement_detail", public_id=public_id)
    try:
        verified = get_invoice(attempt.invoice_id)
        _validate_verified_invoice(attempt, verified)
        apply_verified_xendit_status(
            attempt.id,
            verified,
            verified_event_key(verified),
            signature_valid=False,
        )
    except XenditError as exc:
        messages.error(request, f"Status belum dapat disinkronkan: {exc}")
    else:
        messages.success(request, "Status pembayaran berhasil disinkronkan.")
    return redirect("settlement_detail", public_id=public_id)

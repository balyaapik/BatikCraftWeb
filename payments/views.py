from __future__ import annotations

from datetime import timedelta
import json
import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import AuctionSettlement

from .midtrans import (
    MidtransError,
    create_snap_transaction,
    environment_name,
    get_transaction_status,
    is_enabled,
    parse_amount,
    verified_event_key,
    verify_notification_signature,
)
from .models import PaymentGatewayAttempt
from .services import apply_verified_midtrans_status

logger = logging.getLogger(__name__)


def _authorized_settlement(request, public_id, *, lock=False):
    queryset = AuctionSettlement.objects.select_related(
        "nft",
        "creator",
        "buyer",
    )
    if lock:
        queryset = queryset.select_for_update()
    settlement = get_object_or_404(queryset, public_id=public_id)
    if not (
        request.user.is_superuser
        or request.user.id in {settlement.creator_id, settlement.buyer_id}
    ):
        raise Http404("Invoice tidak ditemukan.")
    return settlement


def _active_attempt(settlement):
    now = timezone.now()
    return (
        settlement.gateway_attempts.filter(
            status__in=[
                PaymentGatewayAttempt.Status.CREATED,
                PaymentGatewayAttempt.Status.PENDING,
            ]
        )
        .filter(expires_at__isnull=True)
        .first()
        or settlement.gateway_attempts.filter(
            status__in=[
                PaymentGatewayAttempt.Status.CREATED,
                PaymentGatewayAttempt.Status.PENDING,
            ],
            expires_at__gt=now,
        ).first()
    )


@login_required
@require_POST
def start_midtrans_checkout(request, public_id):
    if not is_enabled():
        messages.error(
            request,
            "Midtrans belum dikonfigurasi oleh administrator.",
        )
        return redirect("settlement_detail", public_id=public_id)

    with transaction.atomic():
        settlement = _authorized_settlement(request, public_id, lock=True)
        if settlement.buyer_id != request.user.id:
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
        if existing:
            if existing.redirect_url:
                return HttpResponseRedirect(existing.redirect_url)
            messages.info(request, "Checkout sedang dibuat. Silakan coba kembali.")
            return redirect("settlement_detail", public_id=public_id)

        expiry = min(settlement.payment_due_at, timezone.now() + timedelta(days=7))
        order_id = f"BCPAY-{settlement.public_id.hex[:20]}-{uuid.uuid4().hex[:8]}"
        attempt = PaymentGatewayAttempt.objects.create(
            settlement=settlement,
            provider=PaymentGatewayAttempt.Provider.MIDTRANS,
            environment=environment_name(),
            order_id=order_id,
            amount=settlement.amount,
            expires_at=expiry,
        )

    finish_url = request.build_absolute_uri(
        reverse("settlement_detail", args=[settlement.public_id])
    )
    try:
        response = create_snap_transaction(attempt, finish_url)
    except MidtransError as exc:
        PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentGatewayAttempt.Status.FAILED,
            gateway_response={"error": str(exc)},
        )
        logger.warning("Midtrans checkout failed for %s: %s", order_id, exc)
        messages.error(request, f"Checkout gagal dibuat: {exc}")
        return redirect("settlement_detail", public_id=public_id)

    PaymentGatewayAttempt.objects.filter(pk=attempt.pk).update(
        status=PaymentGatewayAttempt.Status.PENDING,
        snap_token=str(response["token"]),
        redirect_url=str(response["redirect_url"]),
        gateway_response=response,
    )
    return HttpResponseRedirect(str(response["redirect_url"]))


@login_required
@require_GET
def settlement_gateway_status(request, public_id):
    settlement = _authorized_settlement(request, public_id)
    attempt = settlement.gateway_attempts.first()
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
                    "paid_at": attempt.paid_at.isoformat()
                    if attempt.paid_at
                    else None,
                }
                if attempt
                else None
            ),
        }
    )


@login_required
@require_POST
def sync_midtrans_status(request, public_id):
    settlement = _authorized_settlement(request, public_id)
    attempt = settlement.gateway_attempts.first()
    if not attempt:
        messages.error(request, "Belum ada transaksi gateway untuk invoice ini.")
        return redirect("settlement_detail", public_id=public_id)
    try:
        verified = get_transaction_status(attempt.order_id)
        if str(verified.get("order_id")) != attempt.order_id:
            raise MidtransError("Order ID hasil verifikasi tidak cocok.")
        if parse_amount(verified.get("gross_amount")) != attempt.amount:
            raise MidtransError("Nominal hasil verifikasi tidak cocok.")
        apply_verified_midtrans_status(
            attempt.id,
            verified,
            verified_event_key(verified),
            signature_valid=False,
        )
    except MidtransError as exc:
        messages.error(request, f"Status belum dapat disinkronkan: {exc}")
    else:
        messages.success(request, "Status pembayaran berhasil disinkronkan.")
    return redirect("settlement_detail", public_id=public_id)


@csrf_exempt
@require_POST
def midtrans_webhook(request):
    if not is_enabled():
        return JsonResponse({"detail": "gateway-disabled"}, status=503)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"detail": "invalid-json"}, status=400)

    order_id = str(payload.get("order_id", "") or "")
    if not order_id:
        return JsonResponse({"detail": "missing-order-id"}, status=400)
    if not verify_notification_signature(payload):
        logger.warning("Rejected invalid Midtrans signature for %s", order_id)
        return JsonResponse({"detail": "invalid-signature"}, status=403)

    attempt = PaymentGatewayAttempt.objects.select_related("settlement").filter(
        order_id=order_id
    ).first()
    if attempt is None:
        return JsonResponse({"detail": "unknown-order-id"}, status=404)
    try:
        notification_amount = parse_amount(payload.get("gross_amount"))
    except MidtransError:
        return JsonResponse({"detail": "invalid-amount"}, status=400)
    if notification_amount != attempt.amount:
        return JsonResponse({"detail": "amount-mismatch"}, status=422)

    try:
        verified = get_transaction_status(order_id)
    except MidtransError as exc:
        logger.error("Midtrans status verification failed for %s: %s", order_id, exc)
        return JsonResponse({"detail": "status-verification-failed"}, status=503)

    if str(verified.get("order_id", "")) != order_id:
        return JsonResponse({"detail": "verified-order-mismatch"}, status=422)
    try:
        verified_amount = parse_amount(verified.get("gross_amount"))
    except MidtransError:
        return JsonResponse({"detail": "invalid-verified-amount"}, status=422)
    if verified_amount != attempt.amount:
        return JsonResponse({"detail": "verified-amount-mismatch"}, status=422)

    _, event, processed = apply_verified_midtrans_status(
        attempt.id,
        verified,
        verified_event_key(verified),
        signature_valid=True,
    )
    return JsonResponse(
        {
            "ok": True,
            "processed": processed,
            "outcome": event.outcome,
        }
    )

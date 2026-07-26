from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.models import AuctionSettlement

from .xendit import (
    XenditError,
    create_invoice,
    environment_name,
    get_invoice,
    invoice_data,
    is_enabled,
    parse_amount,
    verified_event_key,
    verify_webhook_token,
)
from .models import PaymentGatewayAttempt
from .services import apply_verified_xendit_status

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
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .first()
    )


def _validate_verified_invoice(attempt, payload):
    invoice = invoice_data(payload)
    if str(invoice.get("id", "") or "") != attempt.invoice_id:
        raise XenditError("Invoice ID hasil verifikasi tidak cocok.")
    if str(invoice.get("external_id", "") or "") != attempt.order_id:
        raise XenditError("External ID hasil verifikasi tidak cocok.")
    if parse_amount(invoice.get("amount")) != attempt.amount:
        raise XenditError("Nominal hasil verifikasi tidak cocok.")
    return invoice


@login_required
@require_POST
def start_xendit_checkout(request, public_id):
    if not is_enabled():
        messages.error(
            request,
            "Xendit belum dikonfigurasi oleh administrator.",
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
            if existing.invoice_url:
                return HttpResponseRedirect(existing.invoice_url)
            messages.info(request, "Checkout sedang dibuat. Silakan coba kembali.")
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
def sync_xendit_status(request, public_id):
    settlement = _authorized_settlement(request, public_id)
    attempt = settlement.gateway_attempts.first()
    if not attempt:
        messages.error(request, "Belum ada transaksi gateway untuk invoice ini.")
        return redirect("settlement_detail", public_id=public_id)
    try:
        if not attempt.invoice_id:
            raise XenditError("Invoice Xendit belum tersedia.")
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


@csrf_exempt
@require_POST
def xendit_webhook(request):
    if not is_enabled():
        return JsonResponse({"detail": "gateway-disabled"}, status=503)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"detail": "invalid-json"}, status=400)

    if not verify_webhook_token(request.headers.get("x-callback-token")):
        logger.warning("Rejected invalid Xendit webhook token")
        return JsonResponse({"detail": "invalid-webhook-token"}, status=403)

    invoice = invoice_data(payload)
    invoice_id = str(invoice.get("id", "") or "")
    order_id = str(invoice.get("external_id", "") or "")
    if not invoice_id and not order_id:
        return JsonResponse({"detail": "missing-invoice-reference"}, status=400)

    attempts = PaymentGatewayAttempt.objects.select_related("settlement")
    attempt = (
        attempts.filter(invoice_id=invoice_id).first()
        if invoice_id
        else attempts.filter(order_id=order_id).first()
    )
    if attempt is None:
        return JsonResponse({"detail": "unknown-invoice"}, status=404)
    if order_id and order_id != attempt.order_id:
        return JsonResponse({"detail": "order-id-mismatch"}, status=422)
    try:
        notification_amount = parse_amount(invoice.get("amount"))
    except XenditError:
        return JsonResponse({"detail": "invalid-amount"}, status=400)
    if notification_amount != attempt.amount:
        return JsonResponse({"detail": "amount-mismatch"}, status=422)

    try:
        verified = get_invoice(attempt.invoice_id)
    except XenditError as exc:
        logger.error("Xendit invoice verification failed for %s: %s", order_id, exc)
        return JsonResponse({"detail": "status-verification-failed"}, status=503)
    try:
        _validate_verified_invoice(attempt, verified)
    except XenditError:
        return JsonResponse({"detail": "verified-invoice-mismatch"}, status=422)

    _, event, processed = apply_verified_xendit_status(
        attempt.id,
        verified,
        verified_event_key(verified, request.headers.get("webhook-id", "")),
        signature_valid=True,
    )
    return JsonResponse(
        {
            "ok": True,
            "processed": processed,
            "outcome": event.outcome,
        }
    )

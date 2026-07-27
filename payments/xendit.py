from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from core.models import AuctionSettlement

from .models import PaymentGatewaySetting


class XenditError(Exception):
    """Base exception for safe, user-facing Xendit failures."""


class XenditConfigurationError(XenditError):
    pass


class XenditAPIError(XenditError):
    pass


def gateway_config():
    try:
        return PaymentGatewaySetting.objects.get(
            provider=PaymentGatewaySetting.Provider.XENDIT
        )
    except PaymentGatewaySetting.DoesNotExist:
        return None


def is_enabled() -> bool:
    config = gateway_config()
    if config:
        return bool(config.enabled and config.api_key)
    return bool(
        getattr(settings, "XENDIT_ENABLED", False)
        and getattr(settings, "XENDIT_API_KEY", "")
    )


def environment_name() -> str:
    config = gateway_config()
    if config:
        return "production" if config.is_production else "sandbox"
    return (
        "production"
        if getattr(settings, "XENDIT_IS_PRODUCTION", False)
        else "sandbox"
    )


def _api_key() -> str:
    config = gateway_config()
    if config:
        if not config.enabled:
            raise XenditConfigurationError("Payment gateway belum diaktifkan.")
        key = config.api_key.strip()
        if not key:
            raise XenditConfigurationError("Xendit API key belum diisi.")
        return key

    key = str(getattr(settings, "XENDIT_API_KEY", "") or "").strip()
    if not getattr(settings, "XENDIT_ENABLED", False):
        raise XenditConfigurationError("Payment gateway belum diaktifkan.")
    if not key:
        raise XenditConfigurationError("XENDIT_API_KEY belum dikonfigurasi.")
    return key


def _webhook_token() -> str:
    config = gateway_config()
    if config:
        return config.webhook_token.strip()
    return str(getattr(settings, "XENDIT_WEBHOOK_TOKEN", "") or "").strip()


def _authorization_header() -> str:
    token = base64.b64encode(f"{_api_key()}:".encode()).decode()
    return f"Basic {token}"


def _timeout() -> int:
    config = gateway_config()
    if config:
        return config.http_timeout
    return int(getattr(settings, "XENDIT_HTTP_TIMEOUT", 15))


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": _authorization_header(),
            "Content-Type": "application/json",
            "User-Agent": "BatikCraftWeb/1.0",
        },
    )
    try:
        with urlopen(request, timeout=_timeout()) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"detail": raw[:500]}
        raise XenditAPIError(
            f"Xendit menolak permintaan ({exc.code}): {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise XenditAPIError("Xendit tidak dapat dihubungi.") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise XenditAPIError("Respons Xendit bukan JSON yang valid.") from exc


def amount_as_integer(amount: Decimal) -> int:
    integral = amount.to_integral_value()
    if amount != integral:
        raise XenditAPIError("Xendit QRIS memerlukan nominal IDR tanpa pecahan.")
    return int(integral)


def create_invoice(attempt, finish_url: str) -> dict:
    billable = attempt.billable
    if billable is None:
        raise XenditAPIError("Tagihan gateway tidak memiliki objek pembayaran.")
    if attempt.purpose == attempt.Purpose.LISTING_FEE:
        return create_listing_fee_invoice(attempt, finish_url)
    settlement = billable
    due_at = attempt.expires_at or settlement.payment_due_at
    seconds = max(0, (due_at - timezone.now()).total_seconds())
    if seconds < 300:
        raise XenditAPIError("Sisa waktu pembayaran kurang dari lima menit.")

    payload = {
        "external_id": attempt.order_id,
        "amount": amount_as_integer(attempt.amount),
        "currency": "IDR",
        "description": f"Pembayaran lelang {settlement.invoice_number}"[:255],
        "invoice_duration": min(7 * 24 * 60 * 60, math.floor(seconds)),
        "payment_methods": ["QRIS"],
        "success_redirect_url": finish_url,
        "failure_redirect_url": finish_url,
        "should_send_email": False,
    }
    if settlement.buyer.email:
        payload["payer_email"] = settlement.buyer.email

    response = _request_json("POST", "https://api.xendit.co/v2/invoices", payload)
    if not response.get("id") or not response.get("invoice_url"):
        raise XenditAPIError("Xendit tidak mengembalikan invoice URL.")
    return response


def create_listing_fee_invoice(attempt, finish_url: str) -> dict:
    """Buat invoice Xendit untuk fee bidding yang dibayar creator di muka."""
    fee_invoice = attempt.listing_fee
    due_at = attempt.expires_at or fee_invoice.due_at
    seconds = max(0, (due_at - timezone.now()).total_seconds())
    if seconds < 300:
        raise XenditAPIError("Sisa waktu pembayaran kurang dari lima menit.")

    payload = {
        "external_id": attempt.order_id,
        "amount": amount_as_integer(attempt.amount),
        "currency": "IDR",
        "description": (
            f"Fee bidding {fee_invoice.invoice_number} — {fee_invoice.nft.title}"
        )[:255],
        "invoice_duration": min(7 * 24 * 60 * 60, math.floor(seconds)),
        "payment_methods": ["QRIS"],
        "success_redirect_url": finish_url,
        "failure_redirect_url": finish_url,
        "should_send_email": False,
        "items": [
            {
                "name": "Fee bidding listing",
                "quantity": 1,
                "price": amount_as_integer(fee_invoice.fee_amount),
            }
        ],
        "fees": [
            {
                "type": f"PPN {fee_invoice.vat_percent}%",
                "value": amount_as_integer(fee_invoice.vat_amount),
            }
        ],
    }
    if fee_invoice.creator.email:
        payload["payer_email"] = fee_invoice.creator.email

    response = _request_json("POST", "https://api.xendit.co/v2/invoices", payload)
    if not response.get("id") or not response.get("invoice_url"):
        raise XenditAPIError("Xendit tidak mengembalikan invoice URL.")
    return response


def create_payout(payout) -> dict:
    """Kirim perintah disbursement ke Xendit untuk membayar creator."""
    creator = payout.creator
    if not creator.has_payout_account:
        raise XenditConfigurationError(
            "Creator belum melengkapi rekening tujuan payout."
        )
    payload = {
        "reference_id": payout.reference_id,
        "channel_code": payout.bank_name or creator.payout_bank_code,
        "channel_properties": {
            "account_number": payout.account_number or creator.payout_account_number,
            "account_holder_name": (
                payout.account_holder or creator.payout_account_holder
            ),
        },
        "amount": amount_as_integer(payout.amount),
        "currency": "IDR",
        "description": f"Payout lelang {payout.settlement.invoice_number}"[:255],
    }
    response = _request_json(
        "POST",
        "https://api.xendit.co/v2/payouts",
        payload,
    )
    if not response.get("id"):
        raise XenditAPIError("Xendit tidak mengembalikan referensi payout.")
    return response


def classify_payout_status(payload: dict) -> str:
    status = str(payload.get("status", "") or "").upper()
    if status in {"SUCCEEDED", "COMPLETED"}:
        return "success"
    if status in {"FAILED", "REVERSED", "CANCELLED", "CANCELED", "EXPIRED"}:
        return "failed"
    return "processing"


def get_invoice(invoice_id: str) -> dict:
    return _request_json(
        "GET",
        f"https://api.xendit.co/v2/invoices/{quote(invoice_id, safe='')}",
    )


def parse_amount(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise XenditError("Nominal Xendit tidak valid.") from exc


def verify_webhook_token(supplied_token: str | None) -> bool:
    expected_token = _webhook_token()
    # Reject immediately if either side is empty.  An empty expected_token
    # means the webhook secret is not configured — all requests must be
    # refused.  An empty supplied_token means the caller sent no secret.
    # The early return avoids calling hmac.compare_digest("", "") which would
    # return True and let an unauthenticated request through.
    if not expected_token or not supplied_token:
        return False
    return hmac.compare_digest(supplied_token, expected_token)


def invoice_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("id") or data.get("external_id")):
        return data
    return payload


def verified_event_key(payload: dict, webhook_id: str = "") -> str:
    if webhook_id:
        return hashlib.sha256(f"webhook:{webhook_id}".encode()).hexdigest()
    invoice = invoice_data(payload)
    stable_parts = [
        invoice.get("id", ""),
        invoice.get("external_id", ""),
        invoice.get("status", ""),
        invoice.get("amount", ""),
        invoice.get("paid_at", ""),
        invoice.get("updated", ""),
    ]
    return hashlib.sha256("|".join(map(str, stable_parts)).encode()).hexdigest()


def classify_status(payload: dict) -> str:
    status = str(invoice_data(payload).get("status", "") or "").upper()
    if status in {"PAID", "SETTLED"}:
        return "paid"
    if status in {"EXPIRED"}:
        return "expired"
    if status in {"FAILED"}:
        return "failed"
    if status in {"CANCELLED", "CANCELED"}:
        return "cancelled"
    if status in {"REFUNDED"}:
        return "refunded"
    return "pending"


def settlement_payment_method(payment_type: str) -> str:
    if (payment_type or "").upper() in {"QRIS", "QR_CODE"}:
        return AuctionSettlement.PaymentMethod.E_WALLET
    return AuctionSettlement.PaymentMethod.OTHER

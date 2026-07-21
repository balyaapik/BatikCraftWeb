from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from core.models import AuctionSettlement


class MidtransError(Exception):
    """Base exception for safe, user-facing Midtrans failures."""


class MidtransConfigurationError(MidtransError):
    pass


class MidtransAPIError(MidtransError):
    pass


def is_enabled() -> bool:
    return bool(
        getattr(settings, "MIDTRANS_ENABLED", False)
        and getattr(settings, "MIDTRANS_SERVER_KEY", "")
    )


def environment_name() -> str:
    return (
        "production"
        if getattr(settings, "MIDTRANS_IS_PRODUCTION", False)
        else "sandbox"
    )


def _server_key() -> str:
    key = str(getattr(settings, "MIDTRANS_SERVER_KEY", "") or "").strip()
    if not getattr(settings, "MIDTRANS_ENABLED", False):
        raise MidtransConfigurationError("Payment gateway belum diaktifkan.")
    if not key:
        raise MidtransConfigurationError("MIDTRANS_SERVER_KEY belum dikonfigurasi.")
    return key


def _snap_endpoint() -> str:
    if getattr(settings, "MIDTRANS_IS_PRODUCTION", False):
        return "https://app.midtrans.com/snap/v1/transactions"
    return "https://app.sandbox.midtrans.com/snap/v1/transactions"


def _status_endpoint(order_id: str) -> str:
    host = (
        "https://api.midtrans.com"
        if getattr(settings, "MIDTRANS_IS_PRODUCTION", False)
        else "https://api.sandbox.midtrans.com"
    )
    return f"{host}/v2/{quote(order_id, safe='')}/status"


def _authorization_header() -> str:
    token = base64.b64encode(f"{_server_key()}:".encode()).decode()
    return f"Basic {token}"


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
    timeout = int(getattr(settings, "MIDTRANS_HTTP_TIMEOUT", 15))
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"detail": raw[:500]}
        raise MidtransAPIError(
            f"Midtrans menolak permintaan ({exc.code}): {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise MidtransAPIError("Midtrans tidak dapat dihubungi.") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MidtransAPIError("Respons Midtrans bukan JSON yang valid.") from exc


def amount_as_integer(amount: Decimal) -> int:
    integral = amount.to_integral_value()
    if amount != integral:
        raise MidtransAPIError(
            "Midtrans IDR memerlukan nominal tanpa pecahan desimal."
        )
    return int(integral)


def enabled_payments() -> list[str]:
    values = getattr(settings, "MIDTRANS_ALLOWED_PAYMENTS", [])
    return [str(value).strip() for value in values if str(value).strip()]


def create_snap_transaction(attempt, finish_url: str) -> dict:
    settlement = attempt.settlement
    buyer = settlement.buyer
    now = timezone.now()
    due_at = attempt.expires_at or settlement.payment_due_at
    seconds = max(0, (due_at - now).total_seconds())
    if seconds < 300:
        raise MidtransAPIError("Sisa waktu pembayaran kurang dari lima menit.")
    expiry_minutes = min(7 * 24 * 60, max(5, math.ceil(seconds / 60)))
    amount = amount_as_integer(attempt.amount)

    payload = {
        "transaction_details": {
            "order_id": attempt.order_id,
            "gross_amount": amount,
        },
        "item_details": [
            {
                "id": f"NFT-{settlement.nft_id}",
                "price": amount,
                "quantity": 1,
                "name": settlement.nft.title[:50],
                "category": "Digital NFT",
                "merchant_name": "BatikCraft",
            }
        ],
        "customer_details": {
            "first_name": buyer.public_name[:50],
        },
        "expiry": {
            "duration": expiry_minutes,
            "unit": "minute",
        },
        "callbacks": {
            "finish": finish_url,
            "error": finish_url,
        },
    }
    if buyer.email:
        payload["customer_details"]["email"] = buyer.email
    methods = enabled_payments()
    if methods:
        payload["enabled_payments"] = methods

    response = _request_json("POST", _snap_endpoint(), payload)
    if not response.get("token") or not response.get("redirect_url"):
        raise MidtransAPIError("Midtrans tidak mengembalikan checkout URL.")
    return response


def get_transaction_status(order_id: str) -> dict:
    return _request_json("GET", _status_endpoint(order_id))


def expected_signature(payload: dict) -> str:
    raw = "".join(
        [
            str(payload.get("order_id", "")),
            str(payload.get("status_code", "")),
            str(payload.get("gross_amount", "")),
            _server_key(),
        ]
    )
    return hashlib.sha512(raw.encode()).hexdigest()


def verify_notification_signature(payload: dict) -> bool:
    supplied = str(payload.get("signature_key", "") or "")
    return bool(supplied) and hmac.compare_digest(
        supplied.lower(),
        expected_signature(payload).lower(),
    )


def parse_amount(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MidtransAPIError("Nominal gateway tidak valid.") from exc


def verified_event_key(payload: dict) -> str:
    stable_parts = [
        payload.get("order_id", ""),
        payload.get("transaction_id", ""),
        payload.get("transaction_status", ""),
        payload.get("status_code", ""),
        payload.get("gross_amount", ""),
        payload.get("settlement_time", ""),
        payload.get("transaction_time", ""),
    ]
    return hashlib.sha256("|".join(map(str, stable_parts)).encode()).hexdigest()


def classify_status(payload: dict) -> str:
    status = str(payload.get("transaction_status", "") or "").lower()
    fraud_status = str(payload.get("fraud_status", "") or "").lower()
    if status == "settlement":
        return "paid"
    if status == "capture" and fraud_status in {"", "accept"}:
        return "paid"
    if status in {"pending", "authorize"}:
        return "pending"
    if status in {"expire"}:
        return "expired"
    if status in {"cancel"}:
        return "cancelled"
    if status in {"refund", "partial_refund", "chargeback", "partial_chargeback"}:
        return "refunded"
    if status in {"deny", "failure"} or fraud_status == "deny":
        return "failed"
    return "pending"


def settlement_payment_method(payment_type: str) -> str:
    value = (payment_type or "").lower()
    if value in {"gopay", "shopeepay", "qris"}:
        return AuctionSettlement.PaymentMethod.E_WALLET
    if value in {"bank_transfer", "echannel"}:
        return AuctionSettlement.PaymentMethod.BANK_TRANSFER
    return AuctionSettlement.PaymentMethod.OTHER

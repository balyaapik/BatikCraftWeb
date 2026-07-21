from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuctionSettlement, Bid, NFTAsset, User

from .models import PaymentGatewayAttempt, PaymentGatewayEvent


@override_settings(
    SECURE_SSL_REDIRECT=False,
    MIDTRANS_ENABLED=True,
    MIDTRANS_IS_PRODUCTION=False,
    MIDTRANS_SERVER_KEY="SB-Mid-server-test-key",
    MIDTRANS_ALLOWED_PAYMENTS=["qris", "gopay", "shopeepay", "bca_va"],
)
class MidtransPaymentFlowTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator-gateway",
            password="pass12345",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer-gateway",
            password="pass12345",
            role=User.Role.BUYER,
            wallet_address="0xGatewayBuyer",
            email="buyer@example.com",
        )
        nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Mega Mendung Digital",
            status=NFTAsset.Status.AWAITING_PAYMENT,
            starting_price=Decimal("100000.00"),
            auction_starts_at=timezone.now() - timedelta(days=2),
            auction_ends_at=timezone.now() - timedelta(hours=1),
        )
        bid = Bid.objects.create(
            nft=nft,
            bidder=self.buyer,
            amount=Decimal("150000.00"),
        )
        self.settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            amount=bid.amount,
            status=AuctionSettlement.Status.ACCEPTED,
            payment_method=AuctionSettlement.PaymentMethod.OTHER,
            payment_instructions="Bayar melalui gateway.",
            payment_due_at=timezone.now() + timedelta(hours=24),
            accepted_at=timezone.now(),
        )

    @patch("payments.views.create_snap_transaction")
    def test_buyer_creates_midtrans_checkout(self, create_snap):
        create_snap.return_value = {
            "token": "snap-token-test",
            "redirect_url": "https://app.sandbox.midtrans.com/snap/test",
        }
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://app.sandbox.midtrans.com/snap/test",
        )
        attempt = self.settlement.gateway_attempts.get()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(attempt.amount, self.settlement.amount)

    def _attempt(self):
        return PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-TEST-001",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.PENDING,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def _notification(self, status="settlement"):
        payload = {
            "order_id": "BCPAY-TEST-001",
            "status_code": "200",
            "gross_amount": "150000.00",
            "transaction_id": "midtrans-transaction-001",
            "transaction_status": status,
            "payment_type": "gopay",
            "fraud_status": "accept",
            "settlement_time": "2026-07-21 12:00:00",
        }
        raw = (
            payload["order_id"]
            + payload["status_code"]
            + payload["gross_amount"]
            + "SB-Mid-server-test-key"
        )
        payload["signature_key"] = hashlib.sha512(raw.encode()).hexdigest()
        return payload

    @patch("payments.views.get_transaction_status")
    def test_verified_webhook_mints_and_transfers_nft(self, get_status):
        attempt = self._attempt()
        payload = self._notification()
        get_status.return_value = payload
        response = self.client.post(
            reverse("payments:midtrans_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.settlement.refresh_from_db()
        self.settlement.nft.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PAID)
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.MINTED)
        self.assertEqual(self.settlement.nft.status, NFTAsset.Status.SOLD)
        self.assertEqual(self.settlement.nft.current_owner, self.buyer)
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)

        duplicate = self.client.post(
            reverse("payments:midtrans_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["processed"])
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)

    @patch("payments.views.get_transaction_status")
    def test_invalid_signature_never_calls_status_api(self, get_status):
        self._attempt()
        payload = self._notification()
        payload["signature_key"] = "invalid"
        response = self.client.post(
            reverse("payments:midtrans_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        get_status.assert_not_called()
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    @patch("payments.views.get_transaction_status")
    def test_verified_amount_mismatch_is_rejected(self, get_status):
        self._attempt()
        payload = self._notification()
        verified = dict(payload)
        verified["gross_amount"] = "149000.00"
        get_status.return_value = verified
        response = self.client.post(
            reverse("payments:midtrans_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    @patch("payments.views.get_transaction_status")
    def test_pending_webhook_does_not_mint(self, get_status):
        attempt = self._attempt()
        payload = self._notification(status="pending")
        get_status.return_value = payload
        response = self.client.post(
            reverse("payments:midtrans_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.settlement.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

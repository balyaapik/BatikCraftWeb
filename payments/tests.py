import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuctionSettlement, Bid, NFTAsset, User

from .models import PaymentGatewayAttempt, PaymentGatewayEvent


@override_settings(
    SECURE_SSL_REDIRECT=False,
    XENDIT_ENABLED=True,
    XENDIT_IS_PRODUCTION=False,
    XENDIT_API_KEY="xnd_development_test-key",
    XENDIT_WEBHOOK_TOKEN="xendit-webhook-token",
)
class XenditPaymentFlowTests(TestCase):
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

    @patch("payments.views.create_invoice")
    def test_buyer_creates_xendit_checkout(self, create_invoice):
        create_invoice.return_value = {
            "id": "xendit-invoice-001",
            "invoice_url": "https://checkout.xendit.co/web/invoice/test",
        }
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://checkout.xendit.co/web/invoice/test",
        )
        attempt = self.settlement.gateway_attempts.get()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(attempt.amount, self.settlement.amount)
        self.assertEqual(attempt.invoice_id, "xendit-invoice-001")

    def _attempt(self):
        return PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-TEST-001",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.PENDING,
            invoice_id="xendit-invoice-001",
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def _notification(self, status="PAID"):
        return {
            "id": "xendit-invoice-001",
            "external_id": "BCPAY-TEST-001",
            "amount": str(self.settlement.amount),
            "paid_amount": str(self.settlement.amount),
            "status": status,
            "payment_method": "QRIS",
            "paid_at": "2026-07-21T12:00:00.000Z",
        }

    @patch("payments.views.get_invoice")
    def test_verified_webhook_mints_and_transfers_nft(self, get_invoice):
        attempt = self._attempt()
        payload = self._notification()
        get_invoice.return_value = payload
        response = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="xendit-webhook-token",
            HTTP_WEBHOOK_ID="xendit-webhook-001",
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
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="xendit-webhook-token",
            HTTP_WEBHOOK_ID="xendit-webhook-001",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["processed"])
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)

    @patch("payments.views.get_invoice")
    def test_invalid_webhook_token_never_calls_invoice_api(self, get_invoice):
        self._attempt()
        payload = self._notification()
        response = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="invalid",
        )
        self.assertEqual(response.status_code, 403)
        get_invoice.assert_not_called()
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    @patch("payments.views.get_invoice")
    def test_verified_amount_mismatch_is_rejected(self, get_invoice):
        self._attempt()
        payload = self._notification()
        verified = dict(payload)
        verified["amount"] = str(self.settlement.amount - Decimal("1000.00"))
        get_invoice.return_value = verified
        response = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="xendit-webhook-token",
        )
        self.assertEqual(response.status_code, 422)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    @patch("payments.views.get_invoice")
    def test_pending_webhook_does_not_mint(self, get_invoice):
        attempt = self._attempt()
        payload = self._notification(status="PENDING")
        get_invoice.return_value = payload
        response = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="xendit-webhook-token",
        )
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.settlement.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

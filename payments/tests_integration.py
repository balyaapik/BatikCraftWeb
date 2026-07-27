"""
Integration review tests for the complete Xendit payment flow.

Covers every scenario requested:
  1.  Buyer creates checkout (happy path)
  2.  Successful PAID webhook → mint + NFT transfer
  3.  Duplicate webhook → idempotent (no second mint)
  4.  EXPIRED webhook
  5.  FAILED webhook
  6.  Notification amount mismatch (rejected before API call)
  7.  Verified-API amount mismatch (rejected after API call)
  8.  Invalid callback token
  9.  Unknown invoice
  10. CANCELLED webhook
  11. Already-MINTED settlement (mint_verified_settlement guard)
  12. Checkout blocked when settlement not ACCEPTED
  13. Checkout blocked when invoice already past due
  14. Checkout reuses existing active attempt
  15. Checkout marks attempt FAILED when Xendit API errors
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuctionSettlement, Bid, NFTAsset, User

from .models import PaymentGatewayAttempt, PaymentGatewayEvent


# ---------------------------------------------------------------------------
# All tests use settings-based auth (no DB row) so @override_settings works.
# ---------------------------------------------------------------------------
@override_settings(
    SECURE_SSL_REDIRECT=False,
    XENDIT_ENABLED=True,
    XENDIT_IS_PRODUCTION=False,
    XENDIT_API_KEY="xnd_development_test-key",
    XENDIT_WEBHOOK_TOKEN="test-webhook-token-abc",
)
class XenditIntegrationTests(TestCase):
    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator-int",
            password="pass12345",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer-int",
            password="pass12345",
            role=User.Role.BUYER,
            wallet_address="0xIntBuyer",
            email="buyer-int@example.com",
        )
        nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Kawung Digital",
            status=NFTAsset.Status.AWAITING_PAYMENT,
            starting_price=Decimal("200000.00"),
            auction_starts_at=timezone.now() - timedelta(days=3),
            auction_ends_at=timezone.now() - timedelta(hours=2),
        )
        bid = Bid.objects.create(
            nft=nft,
            bidder=self.buyer,
            amount=Decimal("250000.00"),
        )
        self.settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            amount=bid.amount,
            status=AuctionSettlement.Status.ACCEPTED,
            payment_method=AuctionSettlement.PaymentMethod.OTHER,
            payment_instructions="Gateway.",
            payment_due_at=timezone.now() + timedelta(hours=48),
            accepted_at=timezone.now(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_attempt(
        self,
        *,
        order_id="BCPAY-INT-001",
        invoice_id="xi-001",
        status=PaymentGatewayAttempt.Status.PENDING,
        expires_at=None,
    ):
        if expires_at is None:
            expires_at = timezone.now() + timedelta(hours=2)
        return PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id=order_id,
            amount=self.settlement.amount,
            status=status,
            invoice_id=invoice_id,
            expires_at=expires_at,
        )

    def _payload(self, *, xendit_status="PAID", amount=None,
                 invoice_id="xi-001", order_id="BCPAY-INT-001"):
        if amount is None:
            # Total invoice buyer sudah termasuk PPN, jadi selalu turunkan dari
            # settlement agar tes ikut menguji nominal ber-PPN.
            amount = str(self.settlement.amount)
        return {
            "id": invoice_id,
            "external_id": order_id,
            "amount": amount,
            "status": xendit_status,
            "payment_method": "QRIS",
            "paid_at": "2026-07-21T12:00:00.000Z",
        }

    def _post_webhook(self, payload, *, token="test-webhook-token-abc",
                      webhook_id="wh-001"):
        kwargs = {
            "data": json.dumps(payload),
            "content_type": "application/json",
            "HTTP_X_CALLBACK_TOKEN": token,
        }
        if webhook_id:
            kwargs["HTTP_WEBHOOK_ID"] = webhook_id
        return self.client.post(
            reverse("payments:xendit_webhook"), **kwargs
        )

    # ==================================================================
    # Scenario 1 — Buyer creates checkout (happy path)
    # ==================================================================
    @patch("payments.views.create_invoice")
    def test_checkout_creates_attempt_and_redirects(self, mock_create):
        mock_create.return_value = {
            "id": "xi-new",
            "invoice_url": "https://checkout.xendit.co/web/xi-new",
        }
        self.client.force_login(self.buyer)
        resp = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        # Redirects to invoice_url
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://checkout.xendit.co/web/xi-new")

        # One attempt created
        attempt = self.settlement.gateway_attempts.get()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(attempt.provider, PaymentGatewayAttempt.Provider.XENDIT)
        self.assertEqual(attempt.amount, self.settlement.amount)
        self.assertEqual(
            self.settlement.amount,
            self.settlement.subtotal_amount + self.settlement.vat_amount,
        )
        self.assertEqual(attempt.invoice_id, "xi-new")
        self.assertEqual(attempt.invoice_url, "https://checkout.xendit.co/web/xi-new")
        self.assertIsNotNone(attempt.expires_at)

        # create_invoice was called once with the attempt
        mock_create.assert_called_once()

    # ==================================================================
    # Scenario 2 — Successful PAID webhook → mint + NFT transfer
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_paid_webhook_mints_nft_and_transfers_ownership(self, mock_get):
        attempt = self._make_attempt()
        payload = self._payload()
        mock_get.return_value = payload

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["processed"])
        self.assertEqual(data["outcome"], "paid-and-minted")

        # Attempt updated
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.PAID)
        self.assertEqual(attempt.gateway_status, "PAID")
        self.assertIsNotNone(attempt.paid_at)

        # Settlement updated
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.MINTED)
        self.assertIsNotNone(self.settlement.paid_at)
        self.assertIsNotNone(self.settlement.minted_at)
        self.assertIsNotNone(self.settlement.mint_reference)
        self.assertEqual(self.settlement.minted_to_wallet, self.buyer.wallet_address)
        self.assertEqual(
            self.settlement.review_note,
            "Pembayaran diverifikasi otomatis oleh Xendit.",
        )

        # NFT transferred
        self.settlement.nft.refresh_from_db()
        self.assertEqual(self.settlement.nft.status, NFTAsset.Status.SOLD)
        self.assertEqual(self.settlement.nft.current_owner, self.buyer)
        self.assertIsNotNone(self.settlement.nft.minted_at)
        self.assertTrue(self.settlement.nft.token_id.startswith("BC-"))

        # One event created and processed
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)
        event = PaymentGatewayEvent.objects.get()
        self.assertTrue(event.processed)
        self.assertTrue(event.verified_with_api)
        self.assertTrue(event.signature_valid)
        self.assertEqual(event.outcome, "paid-and-minted")

    # ==================================================================
    # Scenario 3 — Duplicate webhook (same webhook-id) → idempotent
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_duplicate_webhook_is_idempotent(self, mock_get):
        self._make_attempt()
        payload = self._payload()
        mock_get.return_value = payload

        first = self._post_webhook(payload, webhook_id="wh-idem-001")
        second = self._post_webhook(payload, webhook_id="wh-idem-001")

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["processed"])

        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["processed"])

        # Only one event row
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)

        # Settlement still MINTED (not double-processed)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.MINTED)

    # ==================================================================
    # Scenario 4 — EXPIRED webhook
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_expired_webhook_updates_attempt_does_not_mint(self, mock_get):
        attempt = self._make_attempt()
        payload = self._payload(xendit_status="EXPIRED")
        mock_get.return_value = payload

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["outcome"], "expired")

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.EXPIRED)

        self.settlement.refresh_from_db()
        # Settlement must NOT be minted
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    # ==================================================================
    # Scenario 5 — FAILED webhook
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_failed_webhook_updates_attempt_does_not_mint(self, mock_get):
        attempt = self._make_attempt()
        payload = self._payload(xendit_status="FAILED")
        mock_get.return_value = payload

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["outcome"], "failed")

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.FAILED)

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    # ==================================================================
    # Scenario 6 — Notification amount mismatch (before API call)
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_notification_amount_mismatch_rejected_before_api(self, mock_get):
        self._make_attempt()
        # Notification claims wrong amount
        payload = self._payload(amount="100.00")

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "amount-mismatch")
        # get_invoice must NOT be called
        mock_get.assert_not_called()

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    # ==================================================================
    # Scenario 7 — Verified-API amount mismatch (after API call)
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_verified_api_amount_mismatch_rejected(self, mock_get):
        self._make_attempt()
        # Notification is fine but the verified response has a different amount
        notification = self._payload()
        verified = self._payload(amount="100.00")
        mock_get.return_value = verified

        resp = self._post_webhook(notification)

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "verified-invoice-mismatch")

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    # ==================================================================
    # Scenario 8 — Invalid callback token
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_invalid_callback_token_returns_403(self, mock_get):
        self._make_attempt()
        payload = self._payload()

        resp = self._post_webhook(payload, token="wrong-token")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "invalid-webhook-token")
        mock_get.assert_not_called()

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    @patch("payments.views.get_invoice")
    def test_missing_callback_token_returns_403(self, mock_get):
        """Empty/absent token must also be rejected (not bypass via compare_digest)."""
        self._make_attempt()
        payload = self._payload()

        resp = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            # No HTTP_X_CALLBACK_TOKEN header at all
        )

        self.assertEqual(resp.status_code, 403)
        mock_get.assert_not_called()

    # ==================================================================
    # Scenario 9 — Unknown invoice
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_unknown_invoice_id_returns_404(self, mock_get):
        # No attempt in DB for this invoice id
        payload = self._payload(invoice_id="xi-does-not-exist")

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "unknown-invoice")
        mock_get.assert_not_called()

    # ==================================================================
    # Scenario 10 — CANCELLED webhook
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_cancelled_webhook_updates_attempt_does_not_mint(self, mock_get):
        attempt = self._make_attempt()
        payload = self._payload(xendit_status="CANCELLED")
        mock_get.return_value = payload

        resp = self._post_webhook(payload)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["outcome"], "cancelled")

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.CANCELLED)

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.ACCEPTED)

    # ==================================================================
    # Scenario 11 — Already MINTED settlement (guard in mint_verified_settlement)
    # ==================================================================
    @patch("payments.views.get_invoice")
    def test_second_paid_webhook_on_minted_settlement_is_noop(self, mock_get):
        """
        If somehow two different PAID webhooks arrive with different webhook-ids
        (so idempotency key differs), the second call must be absorbed by the
        settlement.status == MINTED guard inside mint_verified_settlement.
        """
        self._make_attempt()
        payload = self._payload()
        mock_get.return_value = payload

        # First webhook: mints successfully
        first = self._post_webhook(payload, webhook_id="wh-a")
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["processed"])

        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.MINTED)

        # Second webhook with a DIFFERENT webhook-id (different event_key)
        second = self._post_webhook(payload, webhook_id="wh-b")
        self.assertEqual(second.status_code, 200)
        # The event is new (different key), so processed=True
        self.assertTrue(second.json()["processed"])
        # But outcome is still paid-and-minted because mint_verified_settlement
        # returns early when settlement is already MINTED
        self.assertEqual(second.json()["outcome"], "paid-and-minted")

        # Settlement unchanged (still MINTED, not corrupted)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, AuctionSettlement.Status.MINTED)

        # Two event rows (different keys), both processed
        self.assertEqual(PaymentGatewayEvent.objects.count(), 2)

    # ==================================================================
    # Scenario 12 — Checkout blocked when settlement not ACCEPTED
    # ==================================================================
    @patch("payments.views.create_invoice")
    def test_checkout_blocked_when_settlement_is_invoiced(self, mock_create):
        self.settlement.status = AuctionSettlement.Status.INVOICED
        self.settlement.save(update_fields=["status", "updated_at"])

        self.client.force_login(self.buyer)
        resp = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        # Redirects back to settlement_detail with an error message
        self.assertEqual(resp.status_code, 302)
        mock_create.assert_not_called()
        self.assertEqual(self.settlement.gateway_attempts.count(), 0)

    # ==================================================================
    # Scenario 13 — Checkout blocked when invoice is past due
    # ==================================================================
    @patch("payments.views.create_invoice")
    def test_checkout_blocked_when_invoice_past_due(self, mock_create):
        self.settlement.payment_due_at = timezone.now() - timedelta(seconds=1)
        self.settlement.save(update_fields=["payment_due_at", "updated_at"])

        self.client.force_login(self.buyer)
        resp = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        self.assertEqual(resp.status_code, 302)
        mock_create.assert_not_called()
        self.assertEqual(self.settlement.gateway_attempts.count(), 0)

    # ==================================================================
    # Scenario 14 — Checkout reuses existing active attempt
    # ==================================================================
    @patch("payments.views.create_invoice")
    def test_checkout_reuses_active_attempt(self, mock_create):
        existing = self._make_attempt(invoice_id="xi-existing")
        existing.invoice_url = "https://checkout.xendit.co/web/xi-existing"
        existing.save(update_fields=["invoice_url", "updated_at"])

        self.client.force_login(self.buyer)
        resp = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        # Redirected to existing invoice_url
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://checkout.xendit.co/web/xi-existing")

        # No new attempt created, no new API call
        mock_create.assert_not_called()
        self.assertEqual(self.settlement.gateway_attempts.count(), 1)

    # ==================================================================
    # Scenario 15 — Checkout marks attempt FAILED when Xendit API errors
    # ==================================================================
    @patch("payments.views.create_invoice")
    def test_checkout_marks_failed_on_xendit_api_error(self, mock_create):
        from payments.xendit import XenditAPIError
        mock_create.side_effect = XenditAPIError("Xendit tidak dapat dihubungi.")

        self.client.force_login(self.buyer)
        resp = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        # Redirects back to settlement_detail (not a crash)
        self.assertEqual(resp.status_code, 302)

        # Attempt was created then marked FAILED
        attempt = self.settlement.gateway_attempts.get()
        self.assertEqual(attempt.status, PaymentGatewayAttempt.Status.FAILED)
        self.assertIn("error", attempt.gateway_response)

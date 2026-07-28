from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuctionSettlement, Bid, NFTAsset, User

from .models import PaymentGatewayAttempt


@override_settings(
    SECURE_SSL_REDIRECT=False,
    XENDIT_ENABLED=True,
    XENDIT_IS_PRODUCTION=False,
    XENDIT_API_KEY="xnd_development_checkout-test",
    XENDIT_WEBHOOK_TOKEN="checkout-webhook-token",
)
class CheckoutRecoveryTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator-checkout",
            password="pass12345",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer-checkout",
            password="pass12345",
            role=User.Role.BUYER,
            wallet_address="0xCheckoutBuyer",
            email="buyer-checkout@example.com",
        )
        self.nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Checkout Recovery Batik",
            status=NFTAsset.Status.AWAITING_PAYMENT,
            starting_price=Decimal("100000.00"),
            auction_starts_at=timezone.now() - timedelta(days=2),
            auction_ends_at=timezone.now() - timedelta(hours=1),
        )
        self.bid = Bid.objects.create(
            nft=self.nft,
            bidder=self.buyer,
            amount=Decimal("150000.00"),
        )
        self.settlement = AuctionSettlement.objects.create(
            nft=self.nft,
            winning_bid=self.bid,
            creator=self.creator,
            buyer=self.buyer,
            subtotal_amount=self.bid.amount,
            vat_percent=Decimal("11.00"),
            vat_amount=Decimal("16500.00"),
            amount=Decimal("166500.00"),
            status=AuctionSettlement.Status.ACCEPTED,
            payment_method=AuctionSettlement.PaymentMethod.E_WALLET,
            payment_instructions="Bayar melalui checkout Xendit.",
            payment_due_at=timezone.now() + timedelta(hours=24),
            accepted_at=timezone.now(),
        )
        self.client.force_login(self.buyer)

    @patch("payments.views.create_invoice")
    def test_stale_created_attempt_is_retired_and_checkout_can_retry(
        self, create_invoice
    ):
        stale = PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-STALE-001",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.CREATED,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        PaymentGatewayAttempt.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )
        create_invoice.return_value = {
            "id": "xendit-invoice-retry",
            "invoice_url": "https://checkout.xendit.co/web/invoice/retry",
        }

        response = self.client.post(
            reverse("payments:start_checkout", args=[self.settlement.public_id])
        )

        self.assertRedirects(
            response,
            "https://checkout.xendit.co/web/invoice/retry",
            fetch_redirect_response=False,
        )
        stale.refresh_from_db()
        self.assertEqual(stale.status, PaymentGatewayAttempt.Status.FAILED)
        self.assertEqual(self.settlement.gateway_attempts.count(), 2)
        newest = self.settlement.gateway_attempts.first()
        self.assertEqual(newest.status, PaymentGatewayAttempt.Status.PENDING)
        self.assertEqual(newest.invoice_id, "xendit-invoice-retry")

    def test_settlement_page_can_resume_and_sync_pending_checkout(self):
        PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-PENDING-001",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.PENDING,
            invoice_id="xendit-invoice-pending",
            invoice_url="https://checkout.xendit.co/web/invoice/pending",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.get(
            reverse("settlement_detail", args=[self.settlement.public_id])
        )

        self.assertContains(response, "Lanjutkan checkout Xendit")
        self.assertContains(response, "Cek status pembayaran")
        self.assertContains(
            response,
            "https://checkout.xendit.co/web/invoice/pending",
        )

    @patch("payments.views.get_invoice")
    def test_sync_uses_latest_attempt_that_has_an_invoice_id(self, get_invoice):
        verifiable = PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-VERIFIABLE-001",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.PENDING,
            invoice_id="xendit-invoice-verifiable",
            invoice_url="https://checkout.xendit.co/web/invoice/verifiable",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        PaymentGatewayAttempt.objects.create(
            settlement=self.settlement,
            order_id="BCPAY-FAILED-NEWER",
            amount=self.settlement.amount,
            status=PaymentGatewayAttempt.Status.FAILED,
            expires_at=timezone.now(),
        )
        get_invoice.return_value = {
            "id": verifiable.invoice_id,
            "external_id": verifiable.order_id,
            "amount": str(verifiable.amount),
            "status": "PENDING",
        }

        response = self.client.post(
            reverse("payments:sync_status", args=[self.settlement.public_id])
        )

        self.assertRedirects(
            response,
            reverse("settlement_detail", args=[self.settlement.public_id]),
        )
        get_invoice.assert_called_once_with("xendit-invoice-verifiable")

    @override_settings(XENDIT_ENABLED=False, XENDIT_API_KEY="")
    def test_disabled_gateway_shows_manual_fallback_instead_of_dead_button(self):
        response = self.client.get(
            reverse("settlement_detail", args=[self.settlement.public_id])
        )

        self.assertContains(response, "Checkout otomatis belum aktif")
        self.assertNotContains(response, ">Bayar melalui Xendit</button>")
        self.assertContains(response, "Kirim bukti pembayaran")

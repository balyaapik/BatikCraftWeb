"""Pengujian alur fee bidding creator, PPN 11%, dan payout creator."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuctionSettlement, Bid, NFTAsset, User
from core.services import close_expired_auctions

from .models import (
    CreatorPayout,
    ListingFeeInvoice,
    PaymentGatewayAttempt,
    PaymentGatewaySetting,
    PlatformFeeSetting,
)
from .services import (
    create_creator_payout,
    dispatch_creator_payout,
    issue_listing_fee_invoice,
)

WEBHOOK_TOKEN = "listing-fee-webhook-token"


def _draft_nft(owner, starting_price="200000.00") -> NFTAsset:
    return NFTAsset.objects.create(
        owner=owner,
        title="Sekar Jagad",
        image_url="https://example.com/sekar.png",
        status=NFTAsset.Status.DRAFT,
        starting_price=Decimal(starting_price),
        auction_ends_at=timezone.now() + timedelta(days=3),
    )


class ListingFeeQuoteTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="fee-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )

    def test_fee_is_percentage_of_starting_price_plus_vat(self):
        nft = _draft_nft(self.creator, "200000.00")

        invoice = issue_listing_fee_invoice(nft)

        # Default 5% dari harga terendah, lalu PPN 11% di atas fee.
        self.assertEqual(invoice.base_amount, Decimal("200000.00"))
        self.assertEqual(invoice.fee_percent, Decimal("5.00"))
        self.assertEqual(invoice.fee_amount, Decimal("10000.00"))
        self.assertEqual(invoice.vat_percent, Decimal("11.00"))
        self.assertEqual(invoice.vat_amount, Decimal("1100.00"))
        self.assertEqual(invoice.total_amount, Decimal("11100.00"))
        self.assertEqual(invoice.status, ListingFeeInvoice.Status.PENDING)

    def test_minimum_fee_applies_to_cheap_listings(self):
        nft = _draft_nft(self.creator, "1000.00")

        invoice = issue_listing_fee_invoice(nft)

        # 5% dari 1000 = 50, jauh di bawah fee minimum 10.000.
        self.assertEqual(invoice.fee_amount, Decimal("10000.00"))
        self.assertEqual(invoice.total_amount, Decimal("11100.00"))

    def test_issuing_twice_reuses_the_paid_invoice(self):
        nft = _draft_nft(self.creator)
        invoice = issue_listing_fee_invoice(nft)
        invoice.status = ListingFeeInvoice.Status.PAID
        invoice.save(update_fields=["status", "updated_at"])

        again = issue_listing_fee_invoice(nft)

        self.assertEqual(again.pk, invoice.pk)
        self.assertEqual(ListingFeeInvoice.objects.count(), 1)

    def test_unpaid_invoice_follows_new_starting_price(self):
        nft = _draft_nft(self.creator, "200000.00")
        issue_listing_fee_invoice(nft)

        nft.starting_price = Decimal("400000.00")
        nft.save(update_fields=["starting_price", "updated_at"])
        refreshed = issue_listing_fee_invoice(nft)

        self.assertEqual(refreshed.fee_amount, Decimal("20000.00"))
        self.assertEqual(refreshed.total_amount, Decimal("22200.00"))
        self.assertEqual(ListingFeeInvoice.objects.count(), 1)


class ListingFeeGateTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="gate-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.nft = _draft_nft(self.creator)

    def test_publish_is_blocked_until_fee_is_paid(self):
        self.client.force_login(self.creator)

        response = self.client.post(reverse("nft_publish", args=[self.nft.pk]))

        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.DRAFT)
        self.assertEqual(response["Location"], reverse("creator_dashboard"))
        invoice = ListingFeeInvoice.objects.get(nft=self.nft)
        self.assertEqual(invoice.status, ListingFeeInvoice.Status.PENDING)

    def test_publish_succeeds_once_fee_is_paid(self):
        invoice = issue_listing_fee_invoice(self.nft)
        invoice.status = ListingFeeInvoice.Status.PAID
        invoice.save(update_fields=["status", "updated_at"])
        self.client.force_login(self.creator)

        self.client.post(reverse("nft_publish", args=[self.nft.pk]))

        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.LISTED)


class ListingFeeCheckoutTests(TestCase):
    def setUp(self):
        PaymentGatewaySetting.objects.create(
            provider=PaymentGatewaySetting.Provider.XENDIT,
            enabled=True,
            api_key="xnd_test_key",
            webhook_token=WEBHOOK_TOKEN,
        )
        self.creator = User.objects.create_user(
            username="checkout-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.nft = _draft_nft(self.creator)

    @patch("payments.views.create_invoice")
    def test_checkout_creates_listing_fee_attempt(self, mock_create):
        mock_create.return_value = {
            "id": "xi-fee-1",
            "invoice_url": "https://checkout.xendit.co/fee-1",
        }
        self.client.force_login(self.creator)

        response = self.client.post(
            reverse("payments:start_listing_fee_checkout", args=[self.nft.pk])
        )

        self.assertEqual(response.status_code, 302)
        attempt = PaymentGatewayAttempt.objects.get()
        self.assertEqual(
            attempt.purpose, PaymentGatewayAttempt.Purpose.LISTING_FEE
        )
        self.assertIsNone(attempt.settlement_id)
        self.assertEqual(attempt.amount, Decimal("11100.00"))
        self.assertEqual(attempt.amount, attempt.listing_fee.total_amount)

    def test_other_creator_cannot_pay_someone_elses_fee(self):
        intruder = User.objects.create_user(
            username="intruder",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.client.force_login(intruder)

        response = self.client.post(
            reverse("payments:start_listing_fee_checkout", args=[self.nft.pk])
        )

        self.assertEqual(response.status_code, 404)

    @patch("payments.views.get_invoice")
    @patch("payments.views.create_invoice")
    def test_paid_webhook_marks_fee_paid_and_lists_nft(
        self, mock_create, mock_get
    ):
        mock_create.return_value = {
            "id": "xi-fee-2",
            "invoice_url": "https://checkout.xendit.co/fee-2",
        }
        self.client.force_login(self.creator)
        self.client.post(
            reverse("payments:start_listing_fee_checkout", args=[self.nft.pk])
        )
        attempt = PaymentGatewayAttempt.objects.get()
        verified = {
            "id": "xi-fee-2",
            "external_id": attempt.order_id,
            "amount": str(attempt.amount),
            "status": "PAID",
            "payment_method": "QRIS",
        }
        mock_get.return_value = verified

        response = self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(verified),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN=WEBHOOK_TOKEN,
            HTTP_WEBHOOK_ID="wh-fee-2",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "listing-fee-paid")
        invoice = ListingFeeInvoice.objects.get()
        self.assertEqual(invoice.status, ListingFeeInvoice.Status.PAID)
        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.LISTED)

    @patch("payments.views.get_invoice")
    @patch("payments.views.create_invoice")
    def test_expired_fee_webhook_leaves_nft_as_draft(self, mock_create, mock_get):
        mock_create.return_value = {
            "id": "xi-fee-3",
            "invoice_url": "https://checkout.xendit.co/fee-3",
        }
        self.client.force_login(self.creator)
        self.client.post(
            reverse("payments:start_listing_fee_checkout", args=[self.nft.pk])
        )
        attempt = PaymentGatewayAttempt.objects.get()
        verified = {
            "id": "xi-fee-3",
            "external_id": attempt.order_id,
            "amount": str(attempt.amount),
            "status": "EXPIRED",
        }
        mock_get.return_value = verified

        self.client.post(
            reverse("payments:xendit_webhook"),
            data=json.dumps(verified),
            content_type="application/json",
            HTTP_X_CALLBACK_TOKEN=WEBHOOK_TOKEN,
            HTTP_WEBHOOK_ID="wh-fee-3",
        )

        invoice = ListingFeeInvoice.objects.get()
        self.assertEqual(invoice.status, ListingFeeInvoice.Status.EXPIRED)
        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.DRAFT)


class UnsoldListingStillOwesFeeTests(TestCase):
    """Fee tetap terutang walau karya tidak laku."""

    def setUp(self):
        self.creator = User.objects.create_user(
            username="unsold-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )

    def test_paid_fee_is_not_refunded_when_auction_finds_no_bidder(self):
        nft = _draft_nft(self.creator)
        invoice = issue_listing_fee_invoice(nft)
        invoice.status = ListingFeeInvoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=["status", "paid_at", "updated_at"])
        nft.status = NFTAsset.Status.LISTED
        nft.auction_ends_at = timezone.now() - timedelta(seconds=1)
        nft.save(update_fields=["status", "auction_ends_at", "updated_at"])

        results = close_expired_auctions()

        self.assertEqual(results[0].outcome, "archived")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, ListingFeeInvoice.Status.PAID)
        self.assertEqual(invoice.total_amount, Decimal("11100.00"))


class BuyerInvoiceVatTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="vat-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="vat-buyer",
            password="strong-pass-123",
            role=User.Role.BUYER,
        )

    def _settlement(self, bid_amount="150000.00") -> AuctionSettlement:
        nft = _draft_nft(self.creator)
        nft.status = NFTAsset.Status.LISTED
        nft.save(update_fields=["status", "updated_at"])
        bid = Bid.objects.create(
            nft=nft, bidder=self.buyer, amount=Decimal(bid_amount)
        )
        return AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            subtotal_amount=bid.amount,
            vat_percent=Decimal("11.00"),
            vat_amount=Decimal("16500.00"),
            amount=Decimal("166500.00"),
            payment_instructions="Bayar via gateway.",
            payment_due_at=timezone.now() + timedelta(hours=48),
        )

    def test_total_is_subtotal_plus_eleven_percent(self):
        settlement = self._settlement()

        self.assertEqual(settlement.subtotal_amount, Decimal("150000.00"))
        self.assertEqual(settlement.vat_amount, Decimal("16500.00"))
        self.assertEqual(settlement.amount, Decimal("166500.00"))

    def test_vat_is_recomputed_when_only_amount_is_supplied(self):
        """Pemanggil lama yang hanya mengisi `amount` tetap menghasilkan PPN benar."""
        nft = _draft_nft(self.creator)
        bid = Bid.objects.create(
            nft=nft, bidder=self.buyer, amount=Decimal("100000.00")
        )
        settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            amount=bid.amount,
            payment_instructions="Bayar via gateway.",
            payment_due_at=timezone.now() + timedelta(hours=48),
        )

        self.assertEqual(settlement.subtotal_amount, Decimal("100000.00"))
        self.assertEqual(settlement.vat_amount, Decimal("11000.00"))
        self.assertEqual(settlement.amount, Decimal("111000.00"))


class CreatorPayoutTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="payout-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
            payout_bank_code="ID_BCA",
            payout_account_number="1234567890",
            payout_account_holder="Payout Creator",
        )
        self.buyer = User.objects.create_user(
            username="payout-buyer",
            password="strong-pass-123",
            role=User.Role.BUYER,
        )
        nft = _draft_nft(self.creator)
        bid = Bid.objects.create(
            nft=nft, bidder=self.buyer, amount=Decimal("150000.00")
        )
        self.settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            subtotal_amount=bid.amount,
            vat_percent=Decimal("11.00"),
            vat_amount=Decimal("16500.00"),
            amount=Decimal("166500.00"),
            status=AuctionSettlement.Status.MINTED,
            payment_instructions="Bayar via gateway.",
            payment_due_at=timezone.now() + timedelta(hours=48),
        )

    def test_payout_excludes_vat_collected_from_buyer(self):
        payout = create_creator_payout(self.settlement.pk)

        # Creator menerima nilai bid penuh; PPN buyer bukan hak creator.
        self.assertEqual(payout.amount, Decimal("150000.00"))
        self.assertEqual(payout.status, CreatorPayout.Status.PENDING)
        self.assertEqual(payout.bank_name, "ID_BCA")

    def test_payout_is_created_only_once(self):
        first = create_creator_payout(self.settlement.pk)
        second = create_creator_payout(self.settlement.pk)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CreatorPayout.objects.count(), 1)

    @patch("payments.services.create_payout")
    def test_dispatch_marks_payout_processing(self, mock_payout):
        mock_payout.return_value = {"id": "xpo-1", "status": "ACCEPTED"}
        payout = create_creator_payout(self.settlement.pk)

        dispatched = dispatch_creator_payout(payout.pk)

        self.assertEqual(dispatched.status, CreatorPayout.Status.PROCESSING)
        self.assertEqual(dispatched.payout_reference, "xpo-1")

    @patch("payments.services.create_payout")
    def test_gateway_failure_is_recorded_without_losing_the_payout(
        self, mock_payout
    ):
        from .xendit import XenditAPIError

        mock_payout.side_effect = XenditAPIError("Xendit tidak dapat dihubungi.")
        payout = create_creator_payout(self.settlement.pk)

        dispatched = dispatch_creator_payout(payout.pk)

        self.assertEqual(dispatched.status, CreatorPayout.Status.FAILED)
        self.assertIn("Xendit", dispatched.failure_reason)
        self.assertTrue(CreatorPayout.objects.filter(pk=payout.pk).exists())

    def test_payout_without_bank_account_fails_cleanly(self):
        self.creator.payout_bank_code = ""
        self.creator.payout_account_number = ""
        self.creator.payout_account_holder = ""
        self.creator.save()
        payout = create_creator_payout(self.settlement.pk)

        dispatched = dispatch_creator_payout(payout.pk)

        self.assertEqual(dispatched.status, CreatorPayout.Status.FAILED)
        self.assertIn("rekening", dispatched.failure_reason.lower())


class PlatformFeeSettingTests(TestCase):
    def test_setting_is_singleton(self):
        first = PlatformFeeSetting.load()
        second = PlatformFeeSetting.load()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PlatformFeeSetting.objects.count(), 1)

    def test_changed_rate_only_affects_new_invoices(self):
        creator = User.objects.create_user(
            username="rate-creator",
            password="strong-pass-123",
            role=User.Role.CREATOR,
        )
        old_nft = _draft_nft(creator, "200000.00")
        old_invoice = issue_listing_fee_invoice(old_nft)
        old_invoice.status = ListingFeeInvoice.Status.PAID
        old_invoice.save(update_fields=["status", "updated_at"])

        config = PlatformFeeSetting.load()
        config.listing_fee_percent = Decimal("10.00")
        config.save()

        new_nft = NFTAsset.objects.create(
            owner=creator,
            title="Parang",
            image_url="https://example.com/parang.png",
            status=NFTAsset.Status.DRAFT,
            starting_price=Decimal("200000.00"),
        )
        new_invoice = issue_listing_fee_invoice(new_nft)

        old_invoice.refresh_from_db()
        self.assertEqual(old_invoice.fee_amount, Decimal("10000.00"))
        self.assertEqual(new_invoice.fee_amount, Decimal("20000.00"))

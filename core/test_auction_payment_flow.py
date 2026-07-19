from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .api_views import _can_download_package
from .models import AuctionSettlement, Bid, NFTAsset, User


class AuctionPaymentFlowTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator",
            password="pass12345",
            role=User.Role.CREATOR,
        )
        self.buyer = User.objects.create_user(
            username="buyer",
            password="pass12345",
            role=User.Role.BUYER,
            wallet_address="0xBuyerWallet",
        )
        self.other_buyer = User.objects.create_user(
            username="other",
            password="pass12345",
            role=User.Role.BUYER,
        )
        self.nft = NFTAsset.objects.create(
            owner=self.creator,
            title="Parang Digital",
            status=NFTAsset.Status.LISTED,
            starting_price=Decimal("100000.00"),
            reserve_price=Decimal("120000.00"),
            auction_starts_at=timezone.now() - timedelta(days=2),
            auction_ends_at=timezone.now() - timedelta(hours=1),
            metadata={
                "_studio_source_package": {
                    "storage_name": "nft-packages/test/source.batikpack",
                    "filename": "source.batikpack",
                }
            },
        )
        Bid.objects.create(
            nft=self.nft,
            bidder=self.other_buyer,
            amount=Decimal("125000.00"),
        )
        self.winning_bid = Bid.objects.create(
            nft=self.nft,
            bidder=self.buyer,
            amount=Decimal("150000.00"),
        )

    def _create_invoice(self):
        self.client.force_login(self.creator)
        response = self.client.post(
            reverse("create_auction_invoice", args=[self.nft.pk]),
            {
                "payment_method": (
                    AuctionSettlement.PaymentMethod.BANK_TRANSFER
                ),
                "payment_due_hours": 48,
                "payment_instructions": "Transfer ke rekening pengujian.",
            },
        )
        self.assertEqual(response.status_code, 302)
        return AuctionSettlement.objects.get(nft=self.nft)

    def _complete_payment(self, settlement):
        self.client.force_login(self.buyer)
        self.client.post(
            reverse("accept_auction_invoice", args=[settlement.public_id])
        )
        self.client.post(
            reverse("submit_auction_payment", args=[settlement.public_id]),
            {
                "payment_reference": "BANK-TEST-001",
                "buyer_note": "Sudah ditransfer.",
            },
        )
        self.client.force_login(self.creator)
        return self.client.post(
            reverse("verify_auction_payment", args=[settlement.public_id])
        )

    def test_creator_invoices_highest_bid_after_auction(self):
        settlement = self._create_invoice()
        self.assertEqual(settlement.winning_bid, self.winning_bid)
        self.assertEqual(settlement.buyer, self.buyer)
        self.assertEqual(settlement.amount, Decimal("150000.00"))
        self.nft.refresh_from_db()
        self.assertEqual(self.nft.status, NFTAsset.Status.AWAITING_PAYMENT)

    def test_full_payment_and_registry_mint_flow(self):
        settlement = self._create_invoice()
        response = self._complete_payment(settlement)
        self.assertEqual(response.status_code, 302)
        settlement.refresh_from_db()
        self.nft.refresh_from_db()
        self.assertEqual(settlement.status, AuctionSettlement.Status.MINTED)
        self.assertEqual(self.nft.status, NFTAsset.Status.SOLD)
        self.assertEqual(self.nft.current_owner, self.buyer)
        self.assertTrue(self.nft.token_id)
        self.assertEqual(self.nft.blockchain, "BatikCraft Registry")

    def test_source_package_remains_locked_until_payment_and_mint(self):
        self.assertTrue(_can_download_package(self.nft, self.creator))
        self.assertFalse(_can_download_package(self.nft, self.buyer))

        settlement = self._create_invoice()
        self.nft.refresh_from_db()
        self.assertFalse(_can_download_package(self.nft, self.buyer))

        self._complete_payment(settlement)
        self.nft.refresh_from_db()
        self.assertTrue(_can_download_package(self.nft, self.buyer))
        self.assertFalse(_can_download_package(self.nft, self.other_buyer))

    def test_invoice_cannot_be_created_before_auction_end(self):
        self.nft.auction_ends_at = timezone.now() + timedelta(hours=1)
        self.nft.save(update_fields=["auction_ends_at"])
        self.client.force_login(self.creator)
        self.client.post(
            reverse("create_auction_invoice", args=[self.nft.pk]),
            {
                "payment_method": (
                    AuctionSettlement.PaymentMethod.BANK_TRANSFER
                ),
                "payment_due_hours": 48,
                "payment_instructions": "Transfer.",
            },
        )
        self.assertFalse(
            AuctionSettlement.objects.filter(nft=self.nft).exists()
        )

    def test_non_participant_cannot_open_invoice(self):
        settlement = self._create_invoice()
        stranger = User.objects.create_user(
            username="stranger",
            password="pass12345",
            role=User.Role.BUYER,
        )
        self.client.force_login(stranger)
        response = self.client.get(
            reverse("settlement_detail", args=[settlement.public_id])
        )
        self.assertEqual(response.status_code, 404)

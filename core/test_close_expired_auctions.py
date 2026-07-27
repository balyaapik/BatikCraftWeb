"""Tests for core.services.close_expired_auctions."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AuctionSettlement, Bid, NFTAsset, User
from .services import close_expired_auctions


def _make_users():
    creator = User.objects.create_user(
        username="creator_svc",
        password="pass",
        role=User.Role.CREATOR,
    )
    buyer = User.objects.create_user(
        username="buyer_svc",
        password="pass",
        role=User.Role.BUYER,
    )
    return creator, buyer


def _listed_nft(creator, *, ended=True, reserve=None):
    """Helper to create a LISTED NFT whose auction has (or has not) ended."""
    offset = timedelta(hours=1)
    return NFTAsset.objects.create(
        owner=creator,
        title="Test Batik",
        status=NFTAsset.Status.LISTED,
        starting_price=Decimal("100000.00"),
        reserve_price=reserve,
        auction_starts_at=timezone.now() - timedelta(days=2),
        auction_ends_at=(
            timezone.now() - offset if ended else timezone.now() + offset
        ),
    )


class CloseExpiredAuctionsTests(TestCase):

    def setUp(self):
        self.creator, self.buyer = _make_users()

    # ------------------------------------------------------------------
    # Settlement creation (reserve met)
    # ------------------------------------------------------------------

    def test_creates_settlement_when_reserve_met(self):
        nft = _listed_nft(self.creator, reserve=Decimal("100000.00"))
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        results = close_expired_auctions()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, "settled")
        self.assertIsNotNone(results[0].settlement_id)

        settlement = AuctionSettlement.objects.get(nft=nft)
        self.assertEqual(settlement.status, AuctionSettlement.Status.INVOICED)
        self.assertEqual(settlement.buyer, self.buyer)
        self.assertEqual(settlement.creator, self.creator)
        self.assertEqual(settlement.amount, Decimal("150000.00"))

    def test_nft_status_becomes_awaiting_payment(self):
        nft = _listed_nft(self.creator)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("200000.00"))

        close_expired_auctions()

        nft.refresh_from_db()
        self.assertEqual(nft.status, NFTAsset.Status.AWAITING_PAYMENT)

    def test_highest_bid_wins_when_multiple_bids_exist(self):
        nft = _listed_nft(self.creator)
        other = User.objects.create_user(
            username="other_svc", password="pass", role=User.Role.BUYER
        )
        Bid.objects.create(nft=nft, bidder=other, amount=Decimal("120000.00"))
        winning = Bid.objects.create(
            nft=nft, bidder=self.buyer, amount=Decimal("180000.00")
        )

        close_expired_auctions()

        settlement = AuctionSettlement.objects.get(nft=nft)
        self.assertEqual(settlement.winning_bid, winning)
        self.assertEqual(settlement.buyer, self.buyer)

    def test_no_reserve_price_any_bid_wins(self):
        """NFT with no reserve price → any bid closes the auction."""
        nft = _listed_nft(self.creator, reserve=None)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("1.00"))

        results = close_expired_auctions()

        self.assertEqual(results[0].outcome, "settled")

    # ------------------------------------------------------------------
    # Archive path (no winner)
    # ------------------------------------------------------------------

    def test_archives_nft_when_no_bids(self):
        nft = _listed_nft(self.creator)

        results = close_expired_auctions()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, "archived")
        nft.refresh_from_db()
        self.assertEqual(nft.status, NFTAsset.Status.ARCHIVED)
        self.assertFalse(AuctionSettlement.objects.filter(nft=nft).exists())

    def test_archives_nft_when_reserve_not_met(self):
        nft = _listed_nft(self.creator, reserve=Decimal("500000.00"))
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("100000.00"))

        results = close_expired_auctions()

        self.assertEqual(results[0].outcome, "archived")
        nft.refresh_from_db()
        self.assertEqual(nft.status, NFTAsset.Status.ARCHIVED)
        self.assertFalse(AuctionSettlement.objects.filter(nft=nft).exists())

    # ------------------------------------------------------------------
    # Idempotency / skip guards
    # ------------------------------------------------------------------

    def test_does_not_process_auction_still_running(self):
        nft = _listed_nft(self.creator, ended=False)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        results = close_expired_auctions()

        self.assertEqual(results, [])
        nft.refresh_from_db()
        self.assertEqual(nft.status, NFTAsset.Status.LISTED)

    def test_skips_nft_already_settled(self):
        nft = _listed_nft(self.creator)
        bid = Bid.objects.create(
            nft=nft, bidder=self.buyer, amount=Decimal("150000.00")
        )
        # Manually create a settlement as the creator would have done.
        AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=bid,
            creator=self.creator,
            buyer=self.buyer,
            amount=bid.amount,
            payment_method=AuctionSettlement.PaymentMethod.BANK_TRANSFER,
            payment_instructions="Manual.",
            payment_due_at=timezone.now() + timedelta(hours=48),
        )
        nft.status = NFTAsset.Status.AWAITING_PAYMENT
        nft.save(update_fields=["status", "updated_at"])

        results = close_expired_auctions()

        # The pre-filter excludes already-settled NFTs — results should be empty.
        self.assertEqual(results, [])
        self.assertEqual(AuctionSettlement.objects.filter(nft=nft).count(), 1)

    def test_idempotent_double_run(self):
        nft = _listed_nft(self.creator)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        close_expired_auctions()
        results2 = close_expired_auctions()

        # Second run skips because nft is no longer LISTED.
        self.assertEqual(results2, [])
        self.assertEqual(AuctionSettlement.objects.filter(nft=nft).count(), 1)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @override_settings(AUCTION_CLOSE_PAYMENT_DUE_HOURS=72)
    def test_payment_due_at_respects_setting(self):
        nft = _listed_nft(self.creator)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        before = timezone.now()
        close_expired_auctions()
        after = timezone.now()

        settlement = AuctionSettlement.objects.get(nft=nft)
        expected_min = before + timedelta(hours=72)
        expected_max = after + timedelta(hours=72)
        self.assertGreaterEqual(settlement.payment_due_at, expected_min)
        self.assertLessEqual(settlement.payment_due_at, expected_max)

    # ------------------------------------------------------------------
    # Multiple auctions in one pass
    # ------------------------------------------------------------------

    def test_processes_multiple_nfts_in_one_call(self):
        nft_winner = _listed_nft(self.creator)
        Bid.objects.create(
            nft=nft_winner, bidder=self.buyer, amount=Decimal("150000.00")
        )
        nft_no_bids = _listed_nft(self.creator)

        results = close_expired_auctions()

        outcomes = {r.nft_id: r.outcome for r in results}
        self.assertEqual(outcomes[nft_winner.pk], "settled")
        self.assertEqual(outcomes[nft_no_bids.pk], "archived")

    # ------------------------------------------------------------------
    # Management command smoke-test
    # ------------------------------------------------------------------

    def test_management_command_runs_without_error(self):
        nft = _listed_nft(self.creator)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("close_expired_auctions", stdout=out)
        output = out.getvalue()
        self.assertIn("SETTLED", output)
        self.assertIn(nft.title, output)

    def test_management_command_dry_run_makes_no_changes(self):
        nft = _listed_nft(self.creator)
        Bid.objects.create(nft=nft, bidder=self.buyer, amount=Decimal("150000.00"))

        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("close_expired_auctions", dry_run=True, stdout=out)
        output = out.getvalue()
        self.assertIn("DRY RUN", output)

        nft.refresh_from_db()
        self.assertEqual(nft.status, NFTAsset.Status.LISTED)
        self.assertFalse(AuctionSettlement.objects.filter(nft=nft).exists())

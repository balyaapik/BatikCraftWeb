"""Business-logic services for the core app.

Functions here are framework-agnostic (no HTTP, no request object) so they can
be called safely from management commands, Celery tasks, or tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AuctionSettlement, NFTAsset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _payment_due_hours() -> int:
    """Hours the buyer has to pay after an auction is automatically closed.

    Override via ``AUCTION_CLOSE_PAYMENT_DUE_HOURS`` in settings (default 48).
    """
    return int(getattr(settings, "AUCTION_CLOSE_PAYMENT_DUE_HOURS", 48))


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuctionCloseResult:
    nft_id: int
    nft_title: str
    outcome: str          # "settled" | "archived" | "skipped"
    settlement_id: int | None = None
    invoice_number: str | None = None


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

@transaction.atomic
def _close_single_auction(nft: NFTAsset) -> AuctionCloseResult:
    """Close one expired auction inside a savepoint.

    Must be called from within an outer ``transaction.atomic`` block so that
    ``select_for_update`` works correctly.
    """
    # Re-fetch with a row lock to prevent concurrent command runs from
    # processing the same NFT simultaneously.
    nft = (
        NFTAsset.objects.select_for_update()
        .select_related("owner")
        .prefetch_related("bids__bidder")
        .get(pk=nft.pk)
    )

    # Skip if another process already handled this NFT.
    if nft.status != NFTAsset.Status.LISTED:
        return AuctionCloseResult(
            nft_id=nft.pk,
            nft_title=nft.title,
            outcome="skipped",
        )

    # Skip if a settlement was already created (e.g. creator did it manually).
    if hasattr(nft, "settlement"):
        return AuctionCloseResult(
            nft_id=nft.pk,
            nft_title=nft.title,
            outcome="skipped",
        )

    winning_bid = (
        nft.bids.select_related("bidder")
        .order_by("-amount", "created_at")
        .first()
    )

    reserve_met = (
        winning_bid is not None
        and (
            nft.reserve_price is None
            or winning_bid.amount >= nft.reserve_price
        )
    )

    if reserve_met:
        # --- Happy path: create invoice and await payment ---
        payment_instructions = getattr(
            settings,
            "AUCTION_DEFAULT_PAYMENT_INSTRUCTIONS",
            (
                "Pembayaran diproses melalui Xendit. "
                "Silakan klik tombol 'Bayar dengan QRIS' di halaman invoice."
            ),
        )
        settlement = AuctionSettlement.objects.create(
            nft=nft,
            winning_bid=winning_bid,
            creator=nft.owner,
            buyer=winning_bid.bidder,
            amount=winning_bid.amount,
            payment_method=AuctionSettlement.PaymentMethod.OTHER,
            payment_instructions=payment_instructions,
            payment_due_at=timezone.now() + timedelta(hours=_payment_due_hours()),
        )
        nft.status = NFTAsset.Status.AWAITING_PAYMENT
        nft.save(update_fields=["status", "updated_at"])

        logger.info(
            "Auction closed with winner: NFT %s (pk=%s) → settlement %s "
            "buyer=%s amount=%s",
            nft.title,
            nft.pk,
            settlement.invoice_number,
            winning_bid.bidder.username,
            winning_bid.amount,
        )
        return AuctionCloseResult(
            nft_id=nft.pk,
            nft_title=nft.title,
            outcome="settled",
            settlement_id=settlement.pk,
            invoice_number=settlement.invoice_number,
        )
    else:
        # --- No valid bids or reserve not met: archive the NFT ---
        nft.status = NFTAsset.Status.ARCHIVED
        nft.save(update_fields=["status", "updated_at"])

        reason = (
            "no bids"
            if winning_bid is None
            else f"reserve not met (highest={winning_bid.amount}, reserve={nft.reserve_price})"
        )
        logger.info(
            "Auction closed without winner: NFT %s (pk=%s) — %s",
            nft.title,
            nft.pk,
            reason,
        )
        return AuctionCloseResult(
            nft_id=nft.pk,
            nft_title=nft.title,
            outcome="archived",
        )


def close_expired_auctions() -> Sequence[AuctionCloseResult]:
    """Find all expired, still-listed auctions and close them.

    Returns a list of :class:`AuctionCloseResult` describing what happened to
    each auction.  The function is idempotent: calling it twice on the same
    set of NFTs produces no duplicate settlements.
    """
    now = timezone.now()

    # Candidate NFTs: listed, auction end time has passed, no settlement yet.
    # The settlement guard inside _close_single_auction is the authoritative
    # check; this queryset is just an efficient pre-filter.
    candidates = (
        NFTAsset.objects.filter(
            status=NFTAsset.Status.LISTED,
            auction_ends_at__lte=now,
            auction_ends_at__isnull=False,
        )
        .exclude(settlement__isnull=False)  # skip already-settled
        .only("pk", "title")
    )

    results: list[AuctionCloseResult] = []
    for nft in candidates:
        try:
            result = _close_single_auction(nft)
            results.append(result)
        except Exception:
            logger.exception(
                "Unexpected error while closing auction for NFT pk=%s", nft.pk
            )
    return results

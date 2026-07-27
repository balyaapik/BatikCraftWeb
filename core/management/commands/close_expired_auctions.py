"""Management command: close_expired_auctions

Finds every NFTAsset that is still LISTED but whose auction_ends_at has
passed, then either:

  - creates an AuctionSettlement (status=INVOICED) and sets the NFT to
    AWAITING_PAYMENT when the reserve price is met, or
  - archives the NFT when there are no valid bids or the reserve is not met.

Usage
-----
Run manually::

    python manage.py close_expired_auctions

Run every minute via cron (production)::

    * * * * * /path/to/venv/bin/python /app/manage.py close_expired_auctions \
              >> /var/log/batikcraft/auction_close.log 2>&1

Or via Docker / Kubernetes CronJob — see docs/auction-closing.md.

The command is idempotent: running it twice in a row for the same set of
auctions is harmless.
"""

import logging

from django.core.management.base import BaseCommand

from core.services import close_expired_auctions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Close all expired auctions: create settlements for winners or "
        "archive NFTs with no valid bids."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Print what would happen without writing any database changes. "
                "Useful for smoke-testing in staging."
            ),
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN — no database changes will be made.")
            )
            # Import here to avoid circular dependency at module level.
            from django.utils import timezone
            from core.models import NFTAsset

            now = timezone.now()
            candidates = (
                NFTAsset.objects.filter(
                    status=NFTAsset.Status.LISTED,
                    auction_ends_at__lte=now,
                    auction_ends_at__isnull=False,
                )
                .exclude(settlement__isnull=False)
                .only("pk", "title", "auction_ends_at")
            )
            count = candidates.count()
            if count == 0:
                self.stdout.write("No expired auctions found.")
                return
            for nft in candidates:
                self.stdout.write(
                    f"  Would close: [{nft.pk}] {nft.title!r} "
                    f"(ended {nft.auction_ends_at})"
                )
            self.stdout.write(
                self.style.WARNING(f"Would process {count} auction(s).")
            )
            return

        results = close_expired_auctions()

        settled = [r for r in results if r.outcome == "settled"]
        archived = [r for r in results if r.outcome == "archived"]
        skipped = [r for r in results if r.outcome == "skipped"]

        for r in settled:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  SETTLED  [{r.nft_id}] {r.nft_title!r} "
                    f"→ invoice {r.invoice_number}"
                )
            )
        for r in archived:
            self.stdout.write(
                self.style.WARNING(
                    f"  ARCHIVED [{r.nft_id}] {r.nft_title!r} "
                    "(no bids or reserve not met)"
                )
            )
        for r in skipped:
            self.stdout.write(
                f"  SKIPPED  [{r.nft_id}] {r.nft_title!r} "
                "(already processed)"
            )

        total = len(results)
        if total == 0:
            self.stdout.write("No expired auctions found.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. {len(settled)} settled, {len(archived)} archived, "
                    f"{len(skipped)} skipped (total {total})."
                )
            )

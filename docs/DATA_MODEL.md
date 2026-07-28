# Data Model

Every model, its purpose, and the state machines that govern it.

## Overview

```text
User ──┬── NFTAsset ──┬── Bid
       │              ├── AuctionSettlement ── CreatorPayout
       │              └── ListingFeeInvoice
       ├── ModelAsset ── ModelPurchase
       └── BlogPost

Singletons: MarketplaceSetting · PlatformFeeSetting
            PaymentGatewaySetting · StorageConfiguration
```

---

## core

### User

Extends `AbstractUser`.

| Field | Notes |
| --- | --- |
| `role` | `creator` (Creator / User) or `buyer` |
| `display_name`, `bio`, `avatar` | Public profile |
| `wallet_address` | Display only. **No private key is ever stored.** |
| `timezone_name` | Blank means follow the marketplace default |
| `payout_bank_code`, `payout_account_number`, `payout_account_holder` | Xendit disbursement channel details |

Properties: `public_name` falls back from display name to full name to username;
`active_timezone` resolves the user's choice against the marketplace default;
`has_payout_account` is true only when all three payout fields are filled.

### MarketplaceSetting

Singleton. Holds `default_timezone` (default `Asia/Jakarta`).

Auction deadlines are always stored in UTC. This timezone only controls how times are
displayed and how input without an offset is interpreted, so a creator and a buyer in
different zones still see the same absolute deadline.

### NFTAsset

| Status | Meaning |
| --- | --- |
| `draft` | Created, not listed |
| `listed` | Live on the market |
| `awaiting_payment` | Auction closed, settlement in progress |
| `sold` | Paid and minted |
| `archived` | Withdrawn |

Ownership uses **two** fields, deliberately:

- `owner` always stays the original creator, so attribution and the creator dashboard
  survive a sale.
- `current_owner` holds the buyer after payment and mint.

Pricing is `starting_price` with an optional `reserve_price`; the auction window is
`auction_starts_at` to `auction_ends_at`. Provenance from the desktop is recorded in
`source_project_id` and `source_app_version`, with a unique constraint on
`(owner, source_project_id)` so re-uploading the same project updates rather than
duplicates. Mint results land in `token_id`, `blockchain`, `contract_address`, and
`minted_at`.

### Bid

`nft`, `bidder`, `amount`, `created_at`. Ordered by amount descending, then creation
time, and indexed on `(nft, -amount)` because the running-price check reads it on every
bid.

### AuctionSettlement

One per NFT, one per winning bid.

| Status | Meaning |
| --- | --- |
| `invoiced` | Awaiting buyer approval |
| `accepted` | Awaiting payment |
| `payment_submitted` | Buyer submitted a reference or proof |
| `minted` | Paid, and the NFT has been issued |
| `declined` | Buyer refused |
| `expired` | Deadline passed |
| `cancelled` | Withdrawn |

Payment methods: `bank_transfer`, `e_wallet`, `other`. Identified publicly by a UUID
`public_id` rather than a sequential primary key, so invoice URLs are not enumerable.
Amounts are split into `subtotal_amount`, VAT, and total.

Foreign keys to NFT, bid, creator, and buyer all use `on_delete=PROTECT`. A settled
transaction cannot be silently erased by deleting something it references.

### ModelAsset and ModelPurchase

Trained LoRA models and asset libraries sold between users.

Status: `draft`, `listed`, `archived`. Licence: `personal`, `commercial`, or
`extended`. `ModelPurchase` records who bought what, and gates the download endpoint.

### BlogPost

Editorial content with draft and publish states, automatic slugs, a cover URL, and a
publication timestamp.

---

## payments

### PlatformFeeSetting

Singleton, editable from Django Admin so rates change without a redeploy.

| Field | Default |
| --- | --- |
| `listing_fee_percent` | 5.00 |
| `minimum_listing_fee` | 10,000.00 |
| `vat_percent` | 11.00 |
| `listing_fee_due_hours` | 48 |
| `auto_payout_enabled` | False |

**Rates are copied onto each invoice when it is raised.** Changing a rate never alters
an existing bill. Any code that recomputes a historical invoice from the current
singleton is a bug.

### ListingFeeInvoice

The creator's up-front fee. Status: `pending`, `paid`, `expired`, `cancelled`.

Stores `base_amount` (the starting price the fee derives from) together with
`fee_percent`, `fee_amount`, `vat_percent`, `vat_amount`, and `total_amount` — the rates
as well as the results, so an old invoice can always be explained.

**The fee is non-refundable.** Sold or unsold, the creator pays it.

### CreatorPayout

One per settlement. Status: `pending`, `processing`, `success`, `failed`. Holds the
payout amount, which equals the settlement subtotal — VAT is not the creator's and is
excluded.

### PaymentGatewayAttempt and PaymentGatewayEvent

Gateway request attempts and received webhook events. These exist so a payment dispute
can be reconstructed from stored evidence rather than from memory.

### PaymentGatewaySetting

Singleton holding Xendit configuration. **A row here takes priority over the
`XENDIT_*` environment variables**; the environment is the fallback for fresh
deployments and CI.

---

## storage_config

### StorageConfiguration

Singleton controlling media storage.

| Field | Notes |
| --- | --- |
| `enabled` | Off means local disk; on means Cloudflare R2 |
| `account_id`, `endpoint_override` | Blank endpoint derives the standard R2 endpoint |
| `access_key_id` | Stored in clear |
| `secret_access_key_ciphertext` | Encrypted, not editable, never displayed again |
| `bucket_name`, `location_prefix` | Prefix defaults to `media` |
| `use_signed_urls`, `signed_url_expiry` | Recommended on; 900 seconds default |
| `custom_domain` | Optional public domain |

The secret is encrypted with `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY`, which is separate
from `DJANGO_SECRET_KEY` precisely so the Django key can be rotated without making
stored credentials undecryptable.

---

## Conventions

- All money is `DecimalField(max_digits=18, decimal_places=2)`. Never a float.
- Public-facing identifiers for invoices and settlements are UUIDs, not sequential ids.
- Singletons use `singleton_id` as the primary key with a default of 1.
- Financially significant relations use `on_delete=PROTECT`.
- Timestamps are stored in UTC and rendered per user.

# Architecture

## Scope

BatikCraftWeb owns everything that happens after a design leaves the desktop: public
listings, auctions, bidding, payment, licensing, downloads, and transaction history.

BatikCraft Studio owns creation. The web platform never edits artwork; the desktop
application is never the source of truth for auction state.

## Django Apps

```text
batikcraft_web/     Project settings, root URLconf, ASGI and WSGI entry points
core/               Users, NFTs, bids, settlements, models market, blog, dashboards, API
payments/           Xendit gateway, listing fees, buyer invoices, creator payouts
storage_config/     Runtime-switchable media storage and encrypted R2 credentials
templates/          Django templates
static/             Static assets
```

`core` is deliberately large because users, NFTs, bids, and settlements are one tightly
coupled transactional domain. Splitting them would spread a single database transaction
across app boundaries.

`payments` and `storage_config` are separate because each owns credentials and an
external service, and both must be replaceable without touching the marketplace.

## Request Flow

```text
URLconf  →  view  →  services.py  →  models
                          ↓
                   payments / storage_config
```

Views handle HTTP: authentication, form binding, redirects, and template context.
Business rules live in `services.py`. A view that computes a fee, decides a state
transition, or writes several rows at once has taken on work that belongs one layer down.

## Module Map

| Module | Responsibility |
| --- | --- |
| `core/models.py` | User, MarketplaceSetting, BlogPost, NFTAsset, Bid, AuctionSettlement, ModelAsset, ModelPurchase |
| `core/services.py` | Auction rules, settlement transitions, minting |
| `core/views.py` | Authenticated dashboards and marketplace actions |
| `core/public_views.py` | Unauthenticated pages: home, market, blog, download |
| `core/auth_views.py` | Registration, CAPTCHA login |
| `core/admin_views.py` | The custom administrator dashboard |
| `core/api_views.py`, `core/serializers.py` | The Studio REST API |
| `core/studio_package.py` | Validation of uploaded `.batikcraftnft` and `.batikpack` files |
| `core/ui_language*.py` | Bilingual interface string catalogues |
| `core/timezone_middleware.py` | Activates each user's effective timezone |
| `payments/xendit.py` | Gateway HTTP client |
| `payments/services.py` | Fee calculation, invoice issuing, payout recording |
| `storage_config/backends.py` | Storage backend selected at runtime |
| `storage_config/crypto.py` | Credential encryption at rest |

## Two Dashboards

There is a custom administrator dashboard at `/dashboard/admin/` **and** Django Admin at
`/admin/`. This is intentional. The custom dashboard covers the day-to-day operational
tasks — posts, users, NFTs, bid auditing, storage configuration — with the marketplace's
own vocabulary and access rules. Django Admin remains for advanced and rare work.

Staff and superusers are routed to the custom dashboard on login by
`views.dashboard_router`.

## Money Is Transactional

Every settlement transition runs inside a database transaction with the invoice and NFT
rows locked. Under concurrent requests this is the only thing preventing a double
verification or a double mint. Details and the full state machine are in
[`AUCTION_PAYMENT_FLOW.md`](AUCTION_PAYMENT_FLOW.md).

Fee rates are stored as a singleton row and **copied onto each invoice** at issue time.
Changing a rate never rewrites an existing bill.

## Storage Indirection

Media does not go straight to `MEDIA_ROOT`. `storage_config` chooses a backend at
runtime from a singleton configuration row, so an administrator can move between local
disk and Cloudflare R2 without a restart or a redeploy. Sensitive files —
`.batikmodel` packages and project sources — are streamed through Django after an access
check rather than served by URL.

## Timezones

The marketplace has a default timezone; each user may override it. Auction windows are
stored in UTC and rendered in the viewer's effective timezone by
`timezone_middleware`. Auction closing is driven by a management command:

```bash
python manage.py close_expired_auctions
```

Run it on a schedule. Without it, expired auctions stay open.

## Databases

SQLite for development, PostgreSQL or MySQL 8 for production. CI runs the full suite
against both SQLite and MySQL 8.4 because the two differ in ways that matter here —
transaction isolation, `SELECT … FOR UPDATE` behaviour, and decimal handling.

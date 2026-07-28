# BatikCraftWeb

The Django web platform for the BatikCraft ecosystem: landing pages, blog, creator and
buyer dashboards, an NFT marketplace with live auctions, a model and asset library
marketplace, a REST API for BatikCraft Studio, and an administrator dashboard.

Django 5.1 · Python 3.11+ · SQLite, PostgreSQL, or MySQL 8

---

## Table of Contents

- [What It Does](#what-it-does)
- [Running Locally](#running-locally)
- [Configuration](#configuration)
- [The Studio API](#the-studio-api)
- [Money Flow](#money-flow)
- [Media Storage](#media-storage)
- [Interface Language](#interface-language)
- [Validation](#validation)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Project Team](#project-team)
- [License and Notices](#license-and-notices)

---

## What It Does

**Public site** — editorial landing page with Home, Download, Market, App, and Blog
navigation, plus a news section and a documentation page.

**Accounts** — registration and login with two roles, Creator/User and Buyer. Login is
CAPTCHA protected. Staff and superusers are routed to the admin dashboard automatically.

**Creator dashboard** — profile, NFT drafts, publishing to the market, pricing,
metadata, bidding statistics, settlement invoices, and payout account details.

**Buyer dashboard** — live auctions, bid history, settlement acceptance, payment
submission, and the collection of NFTs received after mint.

**Marketplace** — NFT auctions with transactional bid validation against the running
price and auction window, plus separate markets for trained models and asset libraries.

**Administrator dashboard** — statistics, blog posts, users, NFTs, bid auditing, and
Cloudflare R2 storage configuration, all outside Django Admin. Django Admin remains
available for advanced work.

**Studio API** — token-authenticated REST API so BatikCraft Studio can upload NFTs,
publish them, and manage a model library without leaving the desktop application.

**Payments** — Xendit checkout for creator listing fees and buyer invoices, with webhook
handling, status synchronisation, and recorded creator payouts.

**Storage** — media served from a local VPS directory or Cloudflare R2, switchable from
the admin dashboard without restarting the application.

---

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

| Area | URL |
| --- | --- |
| Public site | `/` |
| Admin dashboard | `/dashboard/admin/` |
| Storage settings | `/dashboard/admin/storage/` |
| Django Admin | `/admin/` |
| Studio API | `/api/v1/` |

An account with `is_staff=True` or `is_superuser=True` is redirected to the admin
dashboard after login.

### Databases

| Database | Setup |
| --- | --- |
| SQLite | Leave `DATABASE_URL` empty. The development default. |
| PostgreSQL | `DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/batikcraft` |
| MySQL 8 | `pip install -r requirements-mysql.txt`, then `DATABASE_URL=mysql://…` |

A Docker MySQL stack is available:

```bash
docker compose -f docker-compose.mysql.yml up --build
```

---

## Configuration

Copy `.env.example` to `.env`. The values that matter most:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django signing key. Must be changed for production. |
| `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY` | Encrypts stored R2 credentials. Keep it **separate** from the secret key so credentials survive a secret key rotation. |
| `DJANGO_DEBUG` | `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames. |
| `DATABASE_URL` | Empty for SQLite; otherwise a database URL. |
| `XENDIT_ENABLED`, `XENDIT_API_KEY`, `XENDIT_WEBHOOK_TOKEN` | Payment gateway. A `PaymentGatewaySetting` row in the admin UI takes priority over these; the environment variables are the fallback for fresh deployments and CI. |
| `BATIKCRAFT_MINT_NETWORK`, `BATIKCRAFT_MINT_CONTRACT_ADDRESS` | Mint registry. Leave at the default until a real on-chain provider is configured. |

Two safety behaviours are worth knowing:

- The application **refuses to start** with `DJANGO_DEBUG=False` while
  `DJANGO_SECRET_KEY` still holds the example value.
- With debug off, HSTS, `SECURE_SSL_REDIRECT`, and `Secure` cookies are enabled by
  default.

**Never put a wallet private key in `.env` or in this repository.**

Fee rates are not configured here. They live in Django Admin under
**Payments → Platform Fee Settings** so they can change without a redeploy.

---

## The Studio API

Base URL: `/api/v1/`. Full reference in [`docs/API.md`](docs/API.md); a Python client
example is in [`docs/studio_client_example.py`](docs/studio_client_example.py).

```http
POST /api/v1/auth/token/          → { "token": "…" }
POST /api/v1/nfts/                → create a draft (JSON image_url or multipart image)
POST /api/v1/nfts/{id}/publish/   → list it on the market
POST /api/v1/nfts/{id}/bids/      → buyer places a bid
```

Every subsequent request carries `Authorization: Token <TOKEN>`. List endpoints are
paginated; a client must follow pages until `next` is `null`.

`GET /api/v1/capabilities/` needs no authentication and reports the contract version,
minimum Studio version, page size, package limits, and feature flags. Clients should
read it before assuming a feature exists.

---

## Money Flow

Two separate charges, documented in full in
[`docs/AUCTION_PAYMENT_FLOW.md`](docs/AUCTION_PAYMENT_FLOW.md).

**Creator listing fee**, paid up front, before the piece goes live: a percentage of the
starting price, subject to a minimum, plus VAT. **Non-refundable** — the creator pays it
whether or not the work sells. Default rates: 5%, minimum Rp10,000, VAT 11%, payable
within 48 hours.

**Buyer invoice**, after the auction: subtotal (the winning bid), VAT, and total. Once
paid, the NFT is minted to the buyer and a payout equal to the subtotal is recorded for
the creator. VAT is not the creator's and is excluded from the payout.

Rates are copied onto each invoice when it is raised, so changing the rates never alters
an existing bill.

Settlement states: `invoiced` → `accepted` → `payment_submitted` → `minted`, with
`declined`, `expired`, and `cancelled` as terminal alternatives. Each transition runs
inside a database transaction with the invoice and NFT rows locked, which is what
prevents a double verification or a double mint.

---

## Media Storage

Media is served either from a local directory on the VPS or from Cloudflare R2. The mode
is switched at `/dashboard/admin/storage/` and takes effect without a restart.

R2 credentials are stored encrypted, and the Secret Access Key is never displayed again
after it is saved. Signed URLs with a private bucket are the recommended configuration;
`.batikmodel` files and source packages are streamed through Django after an access
check rather than exposed directly.

Existing media can be inspected and moved:

```bash
python manage.py migrate_media_to_r2 --dry-run
python manage.py migrate_media_to_r2
```

See [`docs/STORAGE.md`](docs/STORAGE.md).

---

## Interface Language

The interface is available in Indonesian and English. The choice is stored in the
session **and** in a `batikcraft_ui_language` cookie.

The cookie is not redundant. Django flushes the session when a different account logs
in, so without it the language would reset to Indonesian every time a user switched
accounts or logged out.

All interface strings live in `core/ui_language*.py` and are read from templates through
the `{% t "key" %}` tag.

---

## Validation

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
ruff check .
```

GitHub Actions runs all four against SQLite and repeats the migrations, system check,
and full test suite against MySQL 8.4.

---

## Deployment

A complete VPS walkthrough — R2 configuration, media migration, data migration, and
rollback — is in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

Checklist before going live: rotate both secrets, set `DJANGO_DEBUG=False`, fill in
`DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, set `DATABASE_URL`, configure
the payment gateway, and run `migrate` plus `collectstatic`.

---

## Documentation

Start at [`docs/README.md`](docs/README.md).

| Document | Covers |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Apps, request flow, and where logic belongs |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Every model, field, and state machine |
| [`docs/API.md`](docs/API.md) | The Studio REST API |
| [`docs/AUCTION_PAYMENT_FLOW.md`](docs/AUCTION_PAYMENT_FLOW.md) | Auctions, settlement, fees, payouts, minting |
| [`docs/STORAGE.md`](docs/STORAGE.md) | Local and R2 media storage |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | VPS, MySQL, R2, and rollback |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Layout, conventions, and the i18n system |
| [`docs/TESTING.md`](docs/TESTING.md) | Test suite organisation |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Secrets, access control, and reporting |

---

## Project Team

| Name | Handle |
| --- | --- |
| Hasan Nafi Rais | Balyaapik |
| Siti Fadilah Nur Khasanah | Dila |
| Shabrina Enma | shabrina enma |
| Palupi Fitria Ningrum | Wendy_Son |
| Anindya Nareshwari Nugroho | — |

See [`CONTRIBUTORS.md`](CONTRIBUTORS.md) for roles and contribution details.

Parts of this codebase were written with the help of AI coding assistants. All
AI-assisted output was reviewed, tested, and accepted by the team before it was merged.

---

## License and Notices

BatikCraftWeb serves work rooted in batik, a living Indonesian tradition. Motifs listed
on the marketplace carry cultural meaning beyond their sale price. Creators are expected
to credit regional sources where a design derives from a documented historical pattern.

The desktop companion application lives at
[BatikCraftStudio](https://github.com/balyaapik/BatikCraftStudio).

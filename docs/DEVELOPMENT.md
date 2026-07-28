# Development

## Environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

SQLite is the development default — leave `DATABASE_URL` empty.

## Layout

```text
batikcraft_web/     Settings, root URLconf, ASGI and WSGI
core/               Users, NFTs, bids, settlements, models market, blog, dashboards, API
payments/           Xendit, listing fees, buyer invoices, creator payouts
storage_config/     Runtime-switchable media storage, encrypted credentials
templates/          Django templates
static/             Static assets
docs/               This documentation
```

## Where Logic Belongs

```text
URLconf  →  view  →  services.py  →  models
```

Views handle HTTP: authentication, form binding, redirects, template context. Business
rules live in `services.py`.

A view that computes a fee, decides a state transition, or writes several rows at once
has taken on work that belongs one layer down. That matters most in `payments`, where the
same rule has to hold for a web form, an API call, and a webhook.

## Interface Strings

The interface is bilingual, Indonesian and English. Never hard-code user-facing text in a
template.

Catalogues live in `core/ui_language*.py`, split by area:

| File | Covers |
| --- | --- |
| `ui_language.py` | Shared and navigation |
| `ui_language_dashboard.py` | Dashboards |
| `ui_language_detail.py` | Detail pages |
| `ui_language_pages.py` | Public pages |
| `ui_language_extra.py` | Everything else |

Add the key in both languages, then use it from a template:

```django
{% t "market.bid.submit" %}
```

The choice is stored in the session **and** in a `batikcraft_ui_language` cookie. The
cookie is not redundant: Django flushes the session when a different account logs in, so
without it the language would reset to Indonesian on every account switch or logout.

## Timezones

Auction deadlines are stored in UTC. `MarketplaceSetting.default_timezone` sets the
marketplace default, each user may override it with `timezone_name`, and
`core/timezone_middleware.py` activates the effective zone per request.

Rendering a stored UTC value directly, without the middleware's zone, shows the wrong
deadline to anyone outside the default timezone.

## Migrations

`makemigrations --check --dry-run` runs in CI and fails when a model change has no
migration. Generate the migration in the same commit as the model change:

```bash
python manage.py makemigrations core --name add_payout_account_fields
```

Never edit an applied migration; add a new one.

Migration `core.0003_mysql_partial_unique_guards` deserves a mention: MySQL does not
support declarative partial unique constraints, so equivalent integrity is enforced with
generated columns and unique indexes. Django will still warn about the declarative
constraint. That warning is expected.

## Money Code

The rules that are not negotiable:

- Settlement and invoice transitions run inside `transaction.atomic()` with the affected
  rows selected `for_update`.
- Fee rates are copied onto the invoice at issue time. Never recompute a historical bill
  from the current `PlatformFeeSetting`.
- Amounts are `Decimal`, never `float`.

## Package Validation

`core/studio_package.py` validates uploaded `.batikcraftnft` and `.batikpack` files
before they are stored. Uploads arrive from a desktop application over the network;
treat them as untrusted input.

## Scheduled Commands

```bash
python manage.py close_expired_auctions   # closes auctions past their deadline
python manage.py migrate_media_to_r2      # media migration; see STORAGE.md
```

## Style

- `ruff` enforces the lint rules.
- Comments explain *why*. The code already says *what*.
- Keep views thin.

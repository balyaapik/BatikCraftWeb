# Contributing

Thanks for taking an interest in BatikCraftWeb.

## Getting Set Up

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Confirm the checkout is healthy before changing anything:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
ruff check .
```

## Making a Change

1. **Branch** from `main` with a descriptive name.
2. **Write a failing test first** for any behavioural change.
3. **Keep the change focused.** Unrelated cleanups belong in their own commit.
4. **Run all four validation commands.** All must pass.
5. **Write the commit message for a reader who was not there** — the symptom, the root
   cause, and the evidence, not just what you typed.

## Migrations

`makemigrations --check --dry-run` runs in CI and fails if a model change has no
migration. Generate migrations in the same commit as the model change, and give them
readable names:

```bash
python manage.py makemigrations core --name add_payout_account_fields
```

Never edit an applied migration. Add a new one.

## Money and State Transitions

This is the part of the codebase where a mistake costs someone real money. Rules:

- Every settlement or invoice transition runs inside `transaction.atomic()` with the
  affected rows selected `for_update`. This is what prevents a double verification or a
  double mint under concurrent requests.
- Fee rates are **copied onto the invoice** when it is raised. Never recompute a
  historical bill from the current `PlatformFeeSetting`.
- Amounts are `Decimal`, never `float`.
- A test that exercises a payment path must assert the resulting amounts, not just that
  the request returned 200.

## Interface Strings

The interface is bilingual. Do not hard-code user-facing text in a template. Add the key
to the relevant `core/ui_language*.py` catalogue in both Indonesian and English, then use
it:

```django
{% t "market.bid.submit" %}
```

## Secrets

Nothing secret belongs in the repository, in a migration, or in a fixture. R2 credentials
are encrypted at rest with `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY`, which is deliberately
separate from `DJANGO_SECRET_KEY` so the latter can be rotated without losing them.

If you believe you have found a security problem, read
[`docs/SECURITY.md`](docs/SECURITY.md) before opening a public issue.

## Code Style

- `ruff` enforces the lint rules.
- Comments explain *why*. The code already says *what*.
- Views stay thin; business logic belongs in `services.py`.

## Documentation

The documentation is written in English. If your change alters behaviour a user or an API
client can observe, update the relevant file under `docs/` in the same pull request.

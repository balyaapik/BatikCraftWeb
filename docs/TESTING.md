# Testing

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
ruff check .
```

All four run in CI. The suite additionally runs against MySQL 8.4.

Run a subset:

```bash
python manage.py test core.test_auction_payment_flow
python manage.py test payments
```

Coverage:

```bash
coverage run manage.py test && coverage report
```

## Why MySQL Runs Separately in CI

SQLite and MySQL differ in transaction isolation, `SELECT … FOR UPDATE` behaviour, and
decimal handling — exactly the areas the settlement code depends on. A payment test that
passes on SQLite is not evidence that it passes in production.

MySQL also lacks declarative partial unique constraints, so
`core.0003_mysql_partial_unique_guards` enforces those rules with generated columns and
indexes. Only the MySQL job exercises that path.

## Test Map

| File | Covers |
| --- | --- |
| `core/test_auction_payment_flow.py` | Settlement states, verification, minting |
| `core/test_access_control.py` | Who may download what — a security boundary |
| `core/test_studio_api_contract.py` | The Studio REST API contract |
| `core/test_close_expired_auctions.py` | The auction-closing command |
| `core/test_admin_dashboard.py` | The custom administrator dashboard |
| `core/test_timezone_and_studio_origin.py` | Timezone resolution and upload provenance |
| `core/test_library_market_i18n.py` | Bilingual strings on the library market |
| `core/test_auth_layout.py`, `test_auth_viewport.py` | Login and registration layout |
| `core/test_theme_consistency.py`, `test_fullframe_layout.py`, `test_heritage_redesign.py`, `test_bob_page_alignment.py` | Template and layout regressions |
| `payments/test_listing_fee_and_payout.py` | Fee calculation, invoicing, payouts |
| `payments/tests_integration.py` | Gateway integration |
| `storage_config/tests.py` | Storage switching and credential encryption |

## Writing Tests Here

**A payment test asserts amounts.** A 200 response proves nothing about money. Assert
`fee_amount`, `vat_amount`, `total_amount`, and the resulting payout.

**A state-machine test asserts the transition was refused, not just that it errored.**
Double verification and double mint are the failure modes worth guarding.

**An access-control test checks the negative case.** That an owner can download is the
easy half; that a stranger and a losing bidder cannot is the half that matters.

**Rate changes must not rewrite history.** When touching fee logic, add a test that
changes `PlatformFeeSetting` after an invoice is raised and asserts the invoice is
unchanged.

## Naming

Name the test after the behaviour:

```python
def test_publish_is_rejected_while_the_listing_fee_is_unpaid(): ...
def test_losing_bidder_cannot_download_the_source_package(): ...
```

A year from now the name is the only thing explaining why the test exists.

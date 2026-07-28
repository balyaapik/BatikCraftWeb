# Security

## Reporting a Vulnerability

Do not open a public issue for a security problem. Contact the maintainers privately and
give them time to release a fix.

## What Is Never Stored

- **No wallet private key.** `User.wallet_address` is a display field. Nothing in this
  repository holds a key capable of moving an asset.
- **No card numbers, PINs, OTPs, or banking credentials.** Payment runs through Xendit,
  or through a manual reference the buyer supplies.
- **No blockchain transaction hash is fabricated.** The default `BatikCraft Registry`
  issues its own Token ID and mint reference. A value that looks like an on-chain hash
  came from a real provider.

## Secrets

| Secret | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django signing. Rotate as needed. |
| `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY` | Encrypts stored R2 credentials. Kept separate so a Django key rotation does not destroy them. |
| `XENDIT_API_KEY`, `XENDIT_WEBHOOK_TOKEN` | Payment gateway. A `PaymentGatewaySetting` row overrides the environment. |

The application **refuses to start** with `DJANGO_DEBUG=False` while
`DJANGO_SECRET_KEY` still holds the example value. That guard exists because shipping the
example key is the single most damaging configuration mistake available.

Nothing secret belongs in the repository, a migration, or a fixture.

## Transport and Cookies

With `DJANGO_DEBUG=False`, HSTS, `SECURE_SSL_REDIRECT`, and `Secure` cookies are enabled
by default. `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` must be filled in.

## Access Control

Downloads are authorised, not merely obscured:

| Resource | Who may fetch it |
| --- | --- |
| NFT source package | Owner, superuser, or the highest bidder once the auction ended or the status is `sold` |
| Model file | The purchaser with a `paid` purchase, or the seller |
| Payment proof | The transaction's creator, its buyer, or a superuser |

All are streamed through Django after the check. Internal storage URLs are never exposed.

The regression suite includes `core/test_access_control.py`. Treat it as a security
boundary, not as ordinary tests.

## Financial Integrity

- Every settlement transition runs in a transaction with the invoice and NFT rows locked.
  This prevents double verification and double minting under concurrent requests.
- Fee rates are copied onto each invoice at issue time; historical bills are never
  recomputed from current settings.
- Amounts are `Decimal`, never `float`.
- Gateway attempts and webhook events are persisted so a dispute can be reconstructed
  from stored evidence.

## Authentication

Login is CAPTCHA protected (`core/captcha.py`). The Studio API uses DRF token
authentication; `POST /api/v1/auth/logout/` revokes a token.

## Deployment Reminders

- Keep the R2 bucket private with signed URLs on.
- Never add a `location /media/payment-proofs/` block to Nginx.
- Scope the R2 API token to Object Read & Write on the BatikCraft bucket only.

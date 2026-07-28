# BatikCraft Studio REST API

Base URL: `/api/v1/` — locally `http://127.0.0.1:8000/api/v1/`.

All list endpoints use DRF pagination (`results`, `next`, `previous`). A client must
follow pages until `next` is `null`.

---

## 1. Server Capabilities

```http
GET /api/v1/capabilities/
```

No authentication required. Returns the contract version, the minimum Studio version,
the page size, source package limits, the current `billing` rates, and feature flags for
NFTs, bidding, models, the library, package upload, and package download.

Read this before assuming a feature exists.

---

## 2. Obtaining a Token

```http
POST /api/v1/auth/token/
Content-Type: application/json

{"username": "creator_demo", "password": "BatikCraft123!"}
```

```json
{"token": "<TOKEN>"}
```

Every subsequent request carries:

```http
Authorization: Token <TOKEN>
```

Revoke the token:

```http
POST /api/v1/auth/logout/
Authorization: Token <TOKEN>
```

---

## 3. Account Profile

```http
GET   /api/v1/me/
PATCH /api/v1/me/
Authorization: Token <TOKEN>
```

---

## 4. Uploading an NFT or Asset Library

Accepts JSON with an `image_url`, or `multipart/form-data` with an `image` file. An
optional source package is sent as `package_file`:

| Kind | Package extension |
| --- | --- |
| NFT motif | `.batikcraftnft` |
| Asset library | `.batikpack` |

An asset library with `metadata.source_type = "asset_library"` **must** include a
`package_file` before it can be published.

```http
POST /api/v1/nfts/
Authorization: Token <TOKEN>
Content-Type: multipart/form-data
```

Principal fields:

```text
title
description
image or image_url
package_file        (.batikcraftnft / .batikpack; optional for a motif)
source_project_id
source_app_version
starting_price
reserve_price
auction_ends_at
metadata
```

Motif metadata:

```json
{
  "canvas": {"width": 1920, "height": 1920},
  "motifs": ["kawung", "flora"],
  "dominant_colors": ["#29463D", "#D96F5F"]
}
```

Library metadata:

```json
{
  "source_type": "asset_library",
  "library_name": "Pustaka Sekar",
  "library_author": "Balya Rochmadi",
  "library_type": "ornamen",
  "asset_count": 12,
  "sha256": "..."
}
```

`source_project_id` is optional. When supplied it is unique per creator; a second upload
with the same value is answered `400` on that field.

### JSON Fields over Multipart

In `multipart/form-data`, JSON fields are accepted as JSON strings, and simple lists also
accept a comma-separated form:

```text
metadata      = {"canvas": {"width": 1920}}
trigger_words = ["bcr_kawung", "bcr_parang"]
trigger_words = bcr_kawung, bcr_parang
```

---

## 5. Publishing an NFT

```http
POST /api/v1/nfts/{id}/publish/
Authorization: Token <TOKEN>
```

Requirements: an image, `starting_price > 0`, and — for an asset library — a
successfully stored `.batikpack`.

The **listing fee must be paid** before the listing goes live. If it is not, the
endpoint answers `402 Payment Required` with the full breakdown:

```json
{
  "detail": "The listing fee must be settled before the NFT appears on the market.",
  "listing_fee": {
    "status": "pending",
    "invoice_number": "BCFEE-20260727-A1B2C3D4E5",
    "currency": "IDR",
    "base_amount": "200000.00",
    "fee_percent": "5.00",
    "fee_amount": "10000.00",
    "vat_percent": "11.00",
    "vat_amount": "1100.00",
    "total_amount": "11100.00",
    "due_at": "2026-07-29T10:00:00+00:00",
    "paid_at": null,
    "checkout_url": "https://web.batikcraft.id/payments/nfts/12/listing-fee/checkout/",
    "refundable": false
  }
}
```

The Studio opens `checkout_url` in a browser so the creator can pay, then retries
`publish` once the status becomes `paid`.

---

## 5b. The Creator Listing Fee

```http
GET  /api/v1/nfts/{id}/listing-fee/
POST /api/v1/nfts/{id}/listing-fee/
Authorization: Token <TOKEN>
```

`GET` returns an estimate while no invoice has been raised (`status: "not_issued"`), so
the Studio can show the cost before the creator commits to publishing. `POST` raises the
formal invoice.

The rules:

- The fee is a **percentage of the starting price**, subject to a minimum.
- **VAT** is added on top of that fee.
- **The fee is non-refundable.** Sold or unsold, the creator pays the fee and its VAT.
- Current rates are readable from the `billing` block of the capabilities endpoint.

---

## 5c. VAT on the Buyer Invoice

| Field | Meaning |
| --- | --- |
| `subtotal_amount` | The winning bid |
| `vat_amount` | VAT on the subtotal |
| `amount` | Total payable by the buyer |

Once the buyer settles the invoice, the NFT is issued to their account and a payout equal
to `subtotal_amount` is recorded for the creator. VAT is not the creator's and is
excluded from the payout.

---

## 6. Listing NFTs and Bidding

```http
GET  /api/v1/nfts/
GET  /api/v1/nfts/{id}/bids/
POST /api/v1/nfts/{id}/bids/
Authorization: Token <TOKEN>
```

```json
{"amount": "1500000.00"}
```

A bid is rejected when the auction is closed, the bidder is not a buyer account, the
bidder owns the NFT, or the amount does not exceed the running price.

---

## 7. Downloading a Source Package

```http
GET /api/v1/nfts/{id}/package/
Authorization: Token <TOKEN>
```

Access is granted only to the owner, a superuser, or the highest bidder once the auction
has ended or the status is `sold`.

The file is streamed through Django as an attachment. The response carries
`X-BatikCraft-NFT-ID` and `X-BatikCraft-Package-SHA256`. Internal storage URLs are never
exposed.

---

## 8. Model Marketplace

```http
GET  /api/v1/models/
POST /api/v1/models/
POST /api/v1/models/{id}/publish/
POST /api/v1/models/{id}/purchase/
GET  /api/v1/models/{id}/download/
Authorization: Token <TOKEN>
```

Model upload uses multipart with `model_file=.batikmodel`, plus preview, metadata,
price, licence, trigger words, and capabilities.

---

## 9. Account Model Library

```http
GET /api/v1/library/models/
Authorization: Token <TOKEN>
```

Returns purchases with status `paid`, the model metadata, the download count, and a
download URL that still requires the token.

---

## 10. Upload and Storage Limits

The default source package limit is 512 MB, adjustable through the Django setting
`BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE`. Files are written through the active Django
storage backend, so local, S3, and Cloudflare R2 configurations share one API contract.

---

## Client Example

A working Python client is in [`studio_client_example.py`](studio_client_example.py).

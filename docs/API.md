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

Contract `1.4` adds:

```json
{
  "features": {
    "asset_library_sealed_envelope": true,
    "asset_library_installable_download": true
  }
}
```

Read this endpoint before assuming a feature exists.

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

The secure default contract uses `multipart/form-data` with:

- `image`: the preview image;
- `package_file`: a sealed `.batikcraftnft` produced by BatikCraft Studio.

Although the serializer still exposes `image_url` for migration compatibility, the default
`BATIKCRAFT_REQUIRE_STUDIO_PACKAGE=True` setting rejects external image URLs and images
without a matching sealed package.

| Kind | Uploaded package | Downloadable payload |
| --- | --- | --- |
| NFT motif | `.batikcraftnft` | the verified `.batikcraftnft` |
| Asset library | `.batikcraftnft` envelope | embedded installable `.batikpack` |

A standalone `.batikpack` is **not** accepted as provenance evidence because it does not
bind a separately uploaded marketplace preview to the library contents. For an asset
library, Studio creates an envelope such as:

```text
listing.batikcraftnft
├── manifest.json
├── seal.json
├── preview.jpg
├── project/project.json
└── project/assets/library/<pack-id>.batikpack
```

The Web verifier checks the outer archive, the preview checksum, the embedded package
checksum, safe paths, archive limits, the inner manifest, and every file referenced by the
inner manifest. Exactly one `.batikpack` may be embedded.

```http
POST /api/v1/nfts/
Authorization: Token <TOKEN>
Content-Type: multipart/form-data
```

Principal fields:

```text
title
description
image
package_file        (.batikcraftnft)
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
  "embedded_asset_path": "project/assets/library/pustaka-sekar.batikpack",
  "embedded_asset_filename": "pustaka-sekar.batikpack",
  "sha256": "<SHA-256 OF THE EMBEDDED BATIKPACK>"
}
```

When these optional embedded-package metadata fields are supplied, they must match the
values discovered from the sealed envelope. A mismatch is rejected before an NFT record is
kept.

`source_project_id` is optional. When supplied it is unique per creator; a second upload
with the same value is answered `400` on that field.

### JSON Fields over Multipart

In `multipart/form-data`, JSON fields are accepted as JSON strings, and simple lists also
accept a comma-separated form:

```text
metadata       = {"canvas": {"width": 1920}}
trigger_words  = ["bcr_kawung", "bcr_parang"]
trigger_words  = bcr_kawung, bcr_parang
```

---

## 5. Publishing an NFT

```http
POST /api/v1/nfts/{id}/publish/
Authorization: Token <TOKEN>
```

Requirements:

- an image whose checksum matches the envelope preview;
- `starting_price > 0`;
- for an asset library, an extracted `.batikpack` that passed the inner-package verifier;
- a paid creator listing fee.

The **listing fee must be paid** before the listing goes live. If it is not, the endpoint
answers `402 Payment Required` with the full breakdown:

```json
{
  "detail": "Fee bidding harus dilunasi sebelum NFT tayang di market.",
  "listing_fee": {
    "nft_id": 12,
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

Studio stores `listing_fee.nft_id`, opens `checkout_url`, and then retries
`POST /api/v1/nfts/{id}/publish/` for that same draft. It must not upload the source package
again after payment.

---

## 5b. The Creator Listing Fee

```http
GET  /api/v1/nfts/{id}/listing-fee/
POST /api/v1/nfts/{id}/listing-fee/
Authorization: Token <TOKEN>
```

`GET` returns an estimate while no invoice has been raised (`status: "not_issued"`), so
the Studio can show the cost before the creator commits to publishing. `POST` raises the
formal invoice. Both responses include `nft_id`.

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

Access is granted only to:

- the creator who owns the listing;
- a superuser; or
- the buyer after the NFT is `sold` and its settlement is `minted` for that buyer.

The file is streamed through Django as an attachment. Internal storage URLs are never
exposed.

For a normal motif NFT, the endpoint returns its verified `.batikcraftnft`. For an asset
library, it returns the exact installable `.batikpack` extracted from the verified envelope,
not the outer listing wrapper.

Response headers:

```text
X-BatikCraft-NFT-ID
X-BatikCraft-Package-SHA256
X-BatikCraft-Package-Kind
```

`X-BatikCraft-Package-Kind` is `installable_asset_pack` for an asset-library download and
`sealed_listing_envelope` or `source` for other source packages.

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

The default outer source-package upload limit is 512 MB, adjustable through the Django
setting `BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE`. The verifier also limits member count,
single-member size, and total decompressed size for both the outer envelope and the inner
asset pack.

The outer `.batikcraftnft` and the extracted `.batikpack` are stored as separate objects.
The active Django storage backend is used for both, so local, S3, and Cloudflare R2
configurations share one API contract. Deleting the NFT removes both stored objects.

---

## Client Example

A working Python client is in [`studio_client_example.py`](studio_client_example.py).

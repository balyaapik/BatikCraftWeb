# BatikCraft Studio REST API

Base URL lokal: `http://127.0.0.1:8000/api/v1/`

Semua endpoint list memakai pagination DRF (`results`, `next`, `previous`).
BatikCraft Studio 0.2.0 mengikuti seluruh halaman hingga `next` bernilai `null`.

## 1. Kemampuan server

```http
GET /api/v1/capabilities/
```

Endpoint ini tidak memerlukan login dan mengembalikan versi kontrak, versi Studio
minimum, ukuran halaman, batas paket sumber, serta feature flags untuk NFT, bidding,
model, library, upload paket, dan download paket.

## 2. Mendapatkan token

```http
POST /api/v1/auth/token/
Content-Type: application/json

{"username":"creator_demo","password":"BatikCraft123!"}
```

Respons:

```json
{"token":"<TOKEN>"}
```

Semua request Studio berikutnya memakai header:

```http
Authorization: Token <TOKEN>
```

Logout dan pencabutan token:

```http
POST /api/v1/auth/logout/
Authorization: Token <TOKEN>
```

## 3. Membaca atau memperbarui profil akun

```http
GET /api/v1/me/
PATCH /api/v1/me/
Authorization: Token <TOKEN>
```

## 4. Upload NFT atau pustaka aset dari Studio

Endpoint menerima JSON dengan `image_url`, atau `multipart/form-data` dengan file
`image`. Paket sumber opsional dikirim sebagai `package_file`:

- motif NFT: `.batikcraftnft`;
- pustaka aset: `.batikpack`.

Pustaka aset dengan `metadata.source_type = "asset_library"` wajib menyertakan
`package_file` sebelum dapat dipublikasikan.

```http
POST /api/v1/nfts/
Authorization: Token <TOKEN>
Content-Type: multipart/form-data
```

Field utama:

```text
title
 description
 image atau image_url
 package_file (.batikcraftnft / .batikpack, opsional untuk motif)
 source_project_id
 source_app_version
 starting_price
 reserve_price
 auction_ends_at
 metadata
```

Contoh metadata motif:

```json
{
  "canvas": {"width": 1920, "height": 1920},
  "motifs": ["kawung", "flora"],
  "dominant_colors": ["#29463D", "#D96F5F"]
}
```

Contoh metadata pustaka:

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

`source_project_id` opsional. Jika diisi, nilainya unik per creator. Percobaan
upload kedua dijawab `400` pada field `source_project_id`.

### Field JSON melalui multipart

Pada `multipart/form-data`, field JSON diterima sebagai string JSON:

```text
metadata      = {"canvas": {"width": 1920}}
trigger_words = ["bcr_kawung", "bcr_parang"]
trigger_words = bcr_kawung, bcr_parang
```

## 5. Publish NFT

```http
POST /api/v1/nfts/{id}/publish/
Authorization: Token <TOKEN>
```

NFT wajib memiliki gambar dan `starting_price > 0`. Pustaka aset juga wajib memiliki
file `.batikpack` yang berhasil disimpan server.

## 6. Daftar NFT dan bidding

```http
GET /api/v1/nfts/
GET /api/v1/nfts/{id}/bids/
POST /api/v1/nfts/{id}/bids/
Authorization: Token <TOKEN>
```

Payload bid:

```json
{"amount":"1500000.00"}
```

Bid ditolak jika auction tertutup, bidder bukan akun buyer, bidder adalah pemilik,
atau nominal tidak melebihi harga berjalan.

## 7. Unduh paket sumber NFT atau pustaka

```http
GET /api/v1/nfts/{id}/package/
Authorization: Token <TOKEN>
```

Akses hanya diberikan kepada:

- pemilik NFT/pustaka;
- superuser;
- bidder tertinggi setelah waktu auction berakhir atau status menjadi `sold`.

File dialirkan melalui Django sebagai attachment. Respons membawa header
`X-BatikCraft-NFT-ID` dan `X-BatikCraft-Package-SHA256`. URL storage internal tidak
pernah diekspos.

## 8. Marketplace model

```http
GET  /api/v1/models/
POST /api/v1/models/
POST /api/v1/models/{id}/publish/
POST /api/v1/models/{id}/purchase/
GET  /api/v1/models/{id}/download/
Authorization: Token <TOKEN>
```

Upload model menggunakan multipart dengan field `model_file=.batikmodel`, preview,
metadata, harga, lisensi, trigger words, dan capabilities.

## 9. Library model akun

```http
GET /api/v1/library/models/
Authorization: Token <TOKEN>
```

Respons berisi pembelian berstatus `paid`, metadata model, jumlah download, dan URL
unduh yang tetap memerlukan token.

## 10. Batas upload dan penyimpanan

Batas default paket sumber adalah 512 MB dan dapat diubah melalui setting Django
`BATIKCRAFT_MAX_PACKAGE_UPLOAD_SIZE`. File disimpan menggunakan backend storage
Django aktif, sehingga konfigurasi lokal, S3, atau Cloudflare R2 memakai kontrak API
yang sama.

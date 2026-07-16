# BatikCraft Studio REST API

Base URL lokal: `http://127.0.0.1:8000/api/v1/`

## 1. Mendapatkan token

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

## 2. Membaca profil akun

```http
GET /api/v1/me/
Authorization: Token <TOKEN>
```

## 3. Upload NFT dari Studio

Endpoint menerima JSON dengan `image_url`, atau `multipart/form-data` dengan file `image`.

```http
POST /api/v1/nfts/
Authorization: Token <TOKEN>
Content-Type: application/json

{
  "title": "Sekar Jagad Digital",
  "description": "Komposisi dari BatikCraft Studio",
  "image_url": "https://storage.example.com/output.png",
  "source_project_id": "bcstudio-2026-0001",
  "source_app_version": "0.4.0",
  "starting_price": "1250000.00",
  "auction_ends_at": "2026-08-01T20:00:00+07:00",
  "metadata": {
    "canvas": {"width": 1920, "height": 1920},
    "motifs": ["kawung", "flora"],
    "dominant_colors": ["#29463D", "#D96F5F"]
  }
}
```

`source_project_id` bersifat unik per creator: satu project Studio tidak dapat dibuat dua kali oleh akun yang sama.

## 4. Publish ke Market

```http
POST /api/v1/nfts/{id}/publish/
Authorization: Token <TOKEN>
```

NFT wajib memiliki gambar dan `starting_price > 0`.

## 5. Daftar NFT

```http
GET /api/v1/nfts/
Authorization: Token <TOKEN>
```

Creator melihat karya miliknya dan NFT listed. Buyer hanya melihat NFT listed.

## 6. Bidding

```http
POST /api/v1/nfts/{id}/bids/
Authorization: Token <BUYER_TOKEN>
Content-Type: application/json

{"amount":"1500000.00"}
```

Bid ditolak jika auction tertutup, buyer adalah pemilik karya, atau nominal tidak melebihi harga berjalan.

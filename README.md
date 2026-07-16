# BatikCraftWeb

Website Django untuk ekosistem BatikCraft: landing page, blog, creator dashboard, buyer dashboard, NFT marketplace, bidding, REST API BatikCraft Studio, dan dashboard administrator.

## Fitur

- Landing page editorial dengan navigasi Home, Download, Market, App, dan Blog.
- Registrasi dan login multi-role: **Creator/User** atau **Buyer**.
- Creator dashboard untuk profil, draft NFT, publish ke market, harga, metadata, dan statistik bidding.
- Buyer dashboard untuk live auction dan riwayat bidding.
- Dashboard admin khusus untuk statistik, blog/post, pengguna, NFT, dan audit bidding.
- Editor artikel dengan draft, publish/unpublish, slug otomatis, cover URL, dan waktu publikasi.
- REST API dengan token authentication untuk upload NFT dari aplikasi Studio.
- Upload melalui file multipart atau URL gambar.
- Bidding transaksional dengan validasi harga berjalan dan waktu auction.
- Django Admin teknis tetap tersedia untuk pengelolaan tingkat lanjut.
- Data demo, Docker, WhiteNoise, dan GitHub Actions.

## Menjalankan lokal

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Buka `http://127.0.0.1:8000/`.

Akun demo:

- Admin: `admin_demo` / `BatikCraft123!`
- Creator: `creator_demo` / `BatikCraft123!`
- Buyer: `buyer_demo` / `BatikCraft123!`

Dashboard admin tersedia di `http://127.0.0.1:8000/dashboard/admin/`. Akun dengan `is_staff=True` atau `is_superuser=True` otomatis diarahkan ke dashboard admin setelah login.

## API Studio

Dokumentasi lengkap berada di [`docs/API.md`](docs/API.md). Alur utama:

1. `POST /api/v1/auth/token/`
2. `POST /api/v1/nfts/`
3. `POST /api/v1/nfts/{id}/publish/`
4. Buyer melakukan `POST /api/v1/nfts/{id}/bids/`

Contoh client Python tersedia di [`docs/studio_client_example.py`](docs/studio_client_example.py).

## Validasi

```bash
python manage.py check
python manage.py test
ruff check .
```

## Deployment

Salin `.env.example` menjadi `.env`, ganti secret key, matikan debug, isi hostname, lalu gunakan Docker:

```bash
docker compose up --build
```

Untuk production, gunakan PostgreSQL dan object storage (S3/R2) untuk media NFT. Model dan serializer saat ini telah memisahkan `image` dan `image_url`, sehingga migrasi storage dapat dilakukan tanpa mengubah kontrak API utama.

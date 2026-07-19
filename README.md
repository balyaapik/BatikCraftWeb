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
- Docker, WhiteNoise, dan GitHub Actions.

## Menjalankan lokal

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Buka `http://127.0.0.1:8000/`.

Dashboard admin tersedia di `http://127.0.0.1:8000/dashboard/admin/`. Akun dengan `is_staff=True` atau `is_superuser=True` otomatis diarahkan ke dashboard admin setelah login.

## API Studio

Dokumentasi lengkap berada di [`docs/API.md`](docs/API.md). Alur utama:

1. `POST /api/v1/auth/token/`
2. `POST /api/v1/nfts/`
3. `POST /api/v1/nfts/{id}/publish/`
4. Buyer melakukan `POST /api/v1/nfts/{id}/bids/`

Contoh client Python tersedia di [`docs/studio_client_example.py`](docs/studio_client_example.py).

## Bahasa antarmuka

Pilihan bahasa (ID/EN) disimpan di session sekaligus cookie
`batikcraft_ui_language`. Cookie diperlukan karena Django menghapus session saat
akun lain login, sehingga tanpa cookie pilihan bahasa akan kembali ke Indonesia
setiap kali pengguna berganti akun atau logout.

Seluruh teks antarmuka berada di `core/ui_language*.py` dan dipanggil dari
template melalui tag `{% t "kunci" %}`.

## Validasi

```bash
python manage.py check
python manage.py test
ruff check .
```

## Deployment

Salin `.env.example` menjadi `.env`, ganti secret key, matikan debug, isi hostname, lalu gunakan Docker.
Aplikasi menolak start dengan `DJANGO_DEBUG=False` selama `DJANGO_SECRET_KEY` masih memakai nilai contoh.
Dengan debug dimatikan, HSTS, `SECURE_SSL_REDIRECT`, dan cookie `Secure` aktif secara default:

```bash
docker compose up --build
```

File `.batikmodel` dialirkan melalui Django dan tidak pernah dilayani sebagai URL storage publik,
sehingga hak akses pembeli tetap berlaku pada storage apa pun.

Untuk production, gunakan PostgreSQL dan object storage (S3/R2) untuk media NFT. Model dan serializer saat ini telah memisahkan `image` dan `image_url`, sehingga migrasi storage dapat dilakukan tanpa mengubah kontrak API utama.

### Firebase Hosting + Cloud Run

Konfigurasi deployment Firebase Hosting, Cloud Run, Secret Manager, Workload Identity Federation, dan GitHub Actions tersedia di [`docs/FIREBASE_DEPLOYMENT.md`](docs/FIREBASE_DEPLOYMENT.md).

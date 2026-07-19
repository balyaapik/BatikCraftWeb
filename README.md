# BatikCraftWeb

Website Django untuk ekosistem BatikCraft: landing page, blog, creator dashboard, buyer dashboard, NFT marketplace, bidding, REST API BatikCraft Studio, dan dashboard administrator.

## Fitur

- Landing page editorial dengan navigasi Home, Download, Market, App, dan Blog.
- Registrasi dan login multi-role: **Creator/User** atau **Buyer**.
- Creator dashboard untuk profil, draft NFT, publish ke market, harga, metadata, dan statistik bidding.
- Buyer dashboard untuk live auction dan riwayat bidding.
- Dashboard admin khusus untuk statistik, blog/post, pengguna, NFT, audit bidding, dan konfigurasi Cloudflare R2.
- Editor artikel dengan draft, publish/unpublish, slug otomatis, cover URL, dan waktu publikasi.
- REST API dengan token authentication untuk upload NFT dari aplikasi Studio.
- Upload melalui file multipart atau URL gambar.
- Bidding transaksional dengan validasi harga berjalan dan waktu auction.
- Penyimpanan media dinamis: folder lokal VPS atau Cloudflare R2 tanpa restart aplikasi.
- Kredensial R2 disimpan terenkripsi dan Secret Access Key tidak ditampilkan kembali.
- Dukungan database SQLite untuk development, PostgreSQL, serta MySQL 8 dengan pengujian CI terpisah.
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

Konfigurasi R2 tersedia di:

```text
/dashboard/admin/storage/
```

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
python manage.py makemigrations --check --dry-run
python manage.py test
ruff check .
```

GitHub Actions juga menjalankan migrasi, system check, dan seluruh test terhadap MySQL 8.4.

## Deployment VPS

Panduan lengkap deployment VPS, konfigurasi R2, pemindahan media, migrasi data, dan rollback tersedia di:

[`docs/VPS_R2_MYSQL.md`](docs/VPS_R2_MYSQL.md)

Untuk stack MySQL berbasis Docker:

```bash
docker compose -f docker-compose.mysql.yml up --build
```

Untuk instalasi native MySQL, gunakan:

```bash
pip install -r requirements-mysql.txt
```

Salin `.env.example` menjadi `.env`, ganti kedua secret key, matikan debug, isi hostname, dan isi `DATABASE_URL`. Aplikasi menolak start dengan `DJANGO_DEBUG=False` selama `DJANGO_SECRET_KEY` masih memakai nilai contoh.

Dengan debug dimatikan, HSTS, `SECURE_SSL_REDIRECT`, dan cookie `Secure` aktif secara default.

File `.batikmodel` dan paket sumber dialirkan melalui Django setelah pemeriksaan hak akses. Mode R2 yang disarankan tetap memakai signed URL dan bucket privat.

Media lama dapat diperiksa dan dipindahkan dengan:

```bash
python manage.py migrate_media_to_r2 --dry-run
python manage.py migrate_media_to_r2
```

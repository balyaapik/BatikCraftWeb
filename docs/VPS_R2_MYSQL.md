# Deployment VPS: Cloudflare R2 dan MySQL

Panduan ini memindahkan BatikCraftWeb ke VPS dengan:

- Django + Gunicorn;
- Nginx sebagai reverse proxy;
- MySQL 8.0.11+ atau MySQL 8.4 LTS dengan InnoDB;
- Cloudflare R2 sebagai penyimpanan media opsional.

## 1. Instalasi MySQL driver

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y build-essential default-libmysqlclient-dev pkg-config
python -m pip install -r requirements-mysql.txt
```

Untuk pengujian Docker lokal:

```bash
docker compose -f docker-compose.mysql.yml up --build
```

## 2. Buat database MySQL

Masuk sebagai administrator MySQL lalu jalankan:

```sql
CREATE DATABASE batikcraft
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'batikcraft'@'localhost' IDENTIFIED BY 'GANTI_PASSWORD_KUAT';
GRANT ALL PRIVILEGES ON batikcraft.* TO 'batikcraft'@'localhost';
FLUSH PRIVILEGES;
```

Gunakan InnoDB. Konfigurasi Django otomatis mengaktifkan `utf8mb4`, strict mode `STRICT_TRANS_TABLES`, dan isolation level `read committed` ketika `DATABASE_URL` memakai backend MySQL.

```env
DATABASE_URL=mysql://batikcraft:PASSWORD_URL_ENCODED@127.0.0.1:3306/batikcraft
```

Karakter khusus di username atau password harus di-URL-encode.

## 3. Migrasi data dari SQLite atau PostgreSQL

Hentikan sementara proses penulisan data agar snapshot konsisten.

```bash
python manage.py dumpdata \
  --natural-foreign \
  --natural-primary \
  --exclude contenttypes \
  --exclude auth.permission \
  --exclude sessions \
  --indent 2 \
  > batikcraft-data.json
```

Simpan backup database lama dan folder `media/` sebelum melanjutkan.

Ganti `DATABASE_URL` ke MySQL, lalu:

```bash
python manage.py migrate
python manage.py loaddata batikcraft-data.json
python manage.py check --database default
python manage.py test
```

Migration `core.0003_mysql_partial_unique_guards` membuat generated columns dan unique indexes khusus MySQL untuk menjaga aturan berikut:

- satu `source_project_id` per creator;
- satu versi `source_model_id` per seller;
- satu pembelian berstatus `paid` per buyer dan model.

Django dapat tetap menampilkan peringatan bahwa partial unique constraint deklaratif tidak didukung MySQL. Integritas ekuivalennya dijaga oleh indeks MySQL di atas.

## 4. Kunci enkripsi kredensial R2

Buat kunci terpisah dari `DJANGO_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(60))"
```

Simpan di `.env`:

```env
BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY=HASIL_KUNCI_ACAK
```

Jangan mengganti atau menghapus nilai ini tanpa memasukkan ulang Secret Access Key R2. Nilai tersebut dipakai untuk mengenkripsi kredensial R2 di database.

## 5. Konfigurasi Cloudflare R2 dari admin

1. Buat bucket R2 privat.
2. Buat API token dengan izin Object Read & Write hanya untuk bucket BatikCraft.
3. Masuk ke `/dashboard/admin/storage/`.
4. Isi Account ID, Access Key ID, Secret Access Key, dan nama bucket.
5. Pertahankan `Gunakan URL bertanda tangan` agar `.batikmodel` dan `.batikpack` tetap privat.
6. Tekan **Uji koneksi & simpan**.

Endpoint standar dibentuk otomatis:

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

Gunakan `Endpoint khusus` hanya untuk bucket jurisdiction tertentu atau kebutuhan kompatibilitas khusus.

### Custom domain

Custom domain hanya tersedia saat signed URL dimatikan. Mode tersebut membuat object dapat dilayani secara publik dan tidak direkomendasikan untuk bucket yang menyimpan model atau paket sumber berlisensi.

## 6. Migrasi media lokal ke R2

Periksa dahulu tanpa mengunggah:

```bash
python manage.py migrate_media_to_r2 --dry-run
```

Salin semua media:

```bash
python manage.py migrate_media_to_r2
```

Pilihan tambahan:

```bash
# Hanya folder NFT
python manage.py migrate_media_to_r2 --prefix nfts

# Ganti object R2 jika key sama tetapi ukuran berbeda
python manage.py migrate_media_to_r2 --overwrite

# Hapus lokal hanya setelah object R2 terverifikasi
python manage.py migrate_media_to_r2 --delete-local
```

Sebaiknya jalankan tanpa `--delete-local` terlebih dahulu. Setelah website dan unduhan model diuji, buat backup lalu hapus folder media lokal secara terkontrol.

## 7. Deployment Gunicorn

```bash
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn batikcraft_web.wsgi:application --bind 127.0.0.1:8000
```

Nginx tetap melayani `/static/`. Ketika R2 aktif, file media tidak perlu dilayani langsung oleh Nginx. Endpoint unduhan model dan paket sumber tetap mengalirkan file melalui Django setelah pemeriksaan hak akses.

## 8. Rollback

Untuk kembali ke media lokal:

1. Nonaktifkan `Gunakan Cloudflare R2` pada dashboard admin.
2. Pastikan salinan folder `media/` lokal masih tersedia.
3. Restart tidak diperlukan; upload berikutnya langsung menggunakan media lokal.

Untuk rollback database, hentikan aplikasi, pulihkan backup database lama, lalu kembalikan `DATABASE_URL`.

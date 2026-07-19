# Deployment BatikCraftWeb ke Firebase Hosting dan Cloud Run

BatikCraftWeb tetap berjalan sebagai aplikasi Django. Firebase Hosting menjadi domain/CDN dan meneruskan seluruh request ke layanan Cloud Run `batikcraft-web` di region Jakarta (`asia-southeast2`).

## Arsitektur

```text
Firebase Hosting
  -> Cloud Run: Django + Gunicorn
  -> PostgreSQL eksternal (misalnya Neon)
  -> Object storage untuk media (Cloudflare R2 direkomendasikan)
```

Firebase Hosting tidak menjalankan Python secara langsung. Billing Google Cloud harus ditautkan agar Cloud Run dapat digunakan, meskipun pemakaian kecil dapat tetap berada dalam kuota gratis.

## Pengaman biaya yang sudah diterapkan

Workflow deployment mengatur:

- `min-instances=0` agar layanan dapat turun ke nol;
- `max-instances=2` untuk membatasi autoscaling;
- 1 vCPU dan RAM 512 MiB;
- timeout request 60 detik, sesuai batas rewrite Firebase Hosting;
- deployment hanya melalui pemicu manual GitHub Actions;
- PostgreSQL eksternal, bukan Cloud SQL yang selalu aktif.

Tetap buat budget alert pada Google Cloud Billing. Budget alert memberi peringatan dan bukan hard spending cap.

## Prasyarat satu kali

1. Buat atau pilih Firebase project.
2. Tautkan Cloud Billing sehingga project berada pada paket Blaze.
3. Siapkan PostgreSQL dan salin connection string `DATABASE_URL`.
4. Buka Google Cloud Shell pada project tersebut.
5. Pastikan Firebase CLI telah login ke akun yang memiliki akses project.

## Bootstrap otomatis

Setelah perubahan deployment telah digabung ke branch `main`, jalankan:

```bash
git clone https://github.com/balyaapik/BatikCraftWeb.git
cd BatikCraftWeb
chmod +x scripts/bootstrap_firebase_gcp.sh
./scripts/bootstrap_firebase_gcp.sh FIREBASE_PROJECT_ID
```

Script akan meminta `DATABASE_URL` tanpa menampilkannya di terminal, lalu:

- mengaktifkan API yang diperlukan;
- membuat Artifact Registry `batikcraft`;
- membuat service account deployer dan runtime;
- membuat Workload Identity Federation khusus repository ini dan branch `main`;
- membuat secret `django-secret-key` dan `database-url`;
- memberi runtime akses hanya ke Secret Manager;
- memastikan Firebase Hosting site tersedia;
- mengatur GitHub variables/secrets secara otomatis apabila GitHub CLI sudah login.

Script tidak membuat atau menautkan akun billing karena tindakan tersebut membutuhkan persetujuan pemilik akun Google.

## Nilai GitHub yang dibutuhkan

Jika GitHub CLI tidak tersedia saat bootstrap, masukkan nilai yang dicetak script melalui:

`Settings -> Secrets and variables -> Actions`

Repository variables:

```text
GCP_PROJECT_ID
GCP_RUNTIME_SERVICE_ACCOUNT
```

Repository secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_SERVICE_ACCOUNT
```

Tidak perlu membuat atau menyimpan service-account JSON key.

## Deployment pertama

Buka tab **Actions** pada GitHub, pilih workflow **Deploy Firebase and Cloud Run**, lalu klik **Run workflow** dari branch `main`.

Workflow akan:

1. membangun container Django;
2. mendorong image ke Artifact Registry;
3. menjalankan migrasi database sebagai Cloud Run Job;
4. men-deploy Django ke Cloud Run;
5. men-deploy rewrite Firebase Hosting;
6. menampilkan URL Cloud Run dan Firebase Hosting.

URL utama:

```text
https://FIREBASE_PROJECT_ID.web.app
```

## Membuat admin Django

Setelah deployment pertama, jalankan Cloud Run Job sementara dari Google Cloud Shell:

```bash
gcloud run jobs update batikcraft-migrate \
  --region asia-southeast2 \
  --command python \
  --args manage.py,createsuperuser

gcloud run jobs execute batikcraft-migrate \
  --region asia-southeast2 \
  --wait
```

Setelah admin dibuat, deployment berikutnya akan mengembalikan job tersebut ke perintah migrasi secara otomatis.

## Database

Jangan menggunakan SQLite di production. Filesystem Cloud Run bersifat sementara. Gunakan PostgreSQL dengan TLS, misalnya connection string Neon:

```text
postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

Nilai tersebut disimpan sebagai versi secret `database-url`, bukan di repository.

## Media NFT dan `.batikmodel`

Static CSS/JavaScript dilayani oleh WhiteNoise di dalam container. File upload tidak boleh mengandalkan folder `media/` lokal karena dapat hilang ketika instance Cloud Run dihentikan.

Gunakan Cloudflare R2 atau object storage kompatibel S3 sebelum production. File `.batikmodel` harus tetap private dan diakses melalui pemeriksaan izin Django.

## Custom domain

Setelah URL `web.app` berfungsi, custom domain dapat ditambahkan melalui Firebase Console bagian Hosting. Tambahkan domain tersebut ke:

- `DJANGO_ALLOWED_HOSTS`;
- `DJANGO_CSRF_TRUSTED_ORIGINS`.

Nilai default workflow sudah mencakup domain Firebase dan Cloud Run.

## Update secret

```bash
printf '%s' 'NILAI_BARU' | gcloud secrets versions add django-secret-key --data-file=-
printf '%s' 'DATABASE_URL_BARU' | gcloud secrets versions add database-url --data-file=-
```

Jalankan kembali workflow deployment agar revisi Cloud Run memakai versi secret terbaru.

## AI generatif

Jangan menjalankan generasi AI yang membutuhkan waktu lebih dari 60 detik melalui rewrite Firebase Hosting. Buat endpoint berbasis job/queue atau layanan Cloud Run terpisah, lalu simpan hasilnya ke object storage.

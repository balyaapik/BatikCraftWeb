# Midtrans Real-Time Payment Gateway

BatikCraft memakai Midtrans Snap Redirect untuk menerima pembayaran lelang melalui kanal yang diaktifkan merchant, termasuk QRIS, GoPay/ShopeePay, dan virtual account. Mode awal wajib Sandbox.

## Arsitektur

1. Buyer menerima invoice lelang dan menekan **Buka checkout otomatis**.
2. Backend membuat `PaymentGatewayAttempt` dan meminta Snap token dengan Server Key.
3. Buyer diarahkan ke halaman checkout Midtrans.
4. Midtrans mengirim webhook HTTPS ke BatikCraft.
5. BatikCraft memverifikasi signature SHA-512 lalu memanggil GET Status API Midtrans.
6. Nominal dan `order_id` harus cocok dengan invoice.
7. Hanya status `settlement`, atau `capture` dengan fraud status `accept`, yang dianggap lunas.
8. Event diproses secara idempoten. Pembayaran valid menjalankan mint registry dan memindahkan `current_owner` ke buyer.

Frontend callback tidak pernah dipakai sebagai sumber kebenaran pembayaran.

## Konfigurasi

Tambahkan ke `.env` VPS:

```env
MIDTRANS_ENABLED=True
MIDTRANS_IS_PRODUCTION=False
MIDTRANS_MERCHANT_ID=Gxxxxxxxx
MIDTRANS_CLIENT_KEY=SB-Mid-client-xxxxxxxx
MIDTRANS_SERVER_KEY=SB-Mid-server-xxxxxxxx
MIDTRANS_HTTP_TIMEOUT=15
MIDTRANS_ALLOWED_PAYMENTS=qris,gopay,shopeepay,bca_va,bni_va,bri_va,echannel,permata_va
```

Server Key adalah rahasia. Jangan menaruhnya di template, JavaScript, tiket dukungan, screenshot, atau Git.

## Notification URL

Atur **Payment Notification URL** pada dashboard Midtrans:

```text
https://DOMAIN-BATIKCRAFT/payments/midtrans/webhook/
```

Endpoint wajib memakai HTTPS dengan sertifikat publik valid. Jangan tambahkan autentikasi browser atau CSRF pada URL ini; autentikasinya adalah signature Midtrans dan verifikasi GET Status API.

## Sandbox

1. Gunakan seluruh key Sandbox.
2. Biarkan `MIDTRANS_IS_PRODUCTION=False`.
3. Lakukan pembayaran simulasi dari dashboard/simulator Midtrans.
4. Pastikan status attempt berubah menjadi `paid`, settlement menjadi `minted`, dan NFT masuk ke koleksi buyer.
5. Uji webhook duplikat; jumlah `PaymentGatewayEvent` untuk event yang sama harus tetap satu.

## Produksi

Sebelum mengubah `MIDTRANS_IS_PRODUCTION=True`:

- akun merchant sudah disetujui dan kanal QRIS/e-wallet/VA sudah aktif;
- domain dan Notification URL produksi sudah benar;
- Server Key dan Client Key produksi telah dipasang;
- HTTPS, backup database, logging, dan monitoring webhook aktif;
- alur refund/chargeback serta kebijakan sengketa sudah ditetapkan.

Aplikasi menolak penggunaan Server Key Sandbox (`SB-...`) ketika mode produksi aktif.

## Settlement dana creator

Snap menagih atas nama akun merchant BatikCraft. Dana dicairkan oleh Midtrans ke rekening settlement merchant sesuai kontrak merchant. Pembagian atau payout otomatis ke banyak creator memerlukan produk marketplace/split-payment dan proses KYC terpisah; fitur ini tidak menyimpan rekening, PIN, OTP, atau private key creator.

## Deployment

```bash
cd /srv/batikcraft
git fetch origin
git switch main
git pull --ff-only origin main
sudo docker compose -f docker-compose.mysql.yml up -d --build --force-recreate web
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py migrate
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py check --database default
```

Jangan gunakan `docker compose down -v` karena dapat menghapus volume MySQL.

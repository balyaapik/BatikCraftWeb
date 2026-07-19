# Alur Pembayaran Lelang dan Mint NFT

## Ruang lingkup

Implementasi awal memakai invoice dan verifikasi pembayaran manual. BatikCraft tidak menyimpan nomor kartu, PIN, OTP, atau kredensial perbankan. Creator menuliskan instruksi transfer pada invoice dan buyer mengirim nomor referensi atau bukti pembayaran.

## State transaksi

1. `invoiced`: creator menagih bid tertinggi setelah waktu lelang selesai dan reserve price terpenuhi.
2. `accepted`: buyer menyetujui invoice.
3. `payment_submitted`: buyer mengirim referensi atau bukti pembayaran.
4. `minted`: creator telah memastikan dana masuk; sistem menerbitkan token pada BatikCraft Registry dan memasukkan NFT ke koleksi buyer.
5. `declined`, `expired`, atau `cancelled`: transaksi tidak dilanjutkan.

Setiap perubahan penting dilakukan di dalam transaksi database dan baris invoice/NFT dikunci untuk mencegah verifikasi atau mint ganda.

## Kepemilikan

- `NFTAsset.owner` tetap menyimpan creator asli agar atribusi karya dan dashboard creator tidak hilang.
- `NFTAsset.current_owner` menyimpan buyer setelah pembayaran terverifikasi.
- NFT yang selesai berubah menjadi status `sold` dan muncul pada koleksi NFT dashboard buyer.

## Mint awal

Secara default sistem memakai `BatikCraft Registry` sebagai registry internal dan menghasilkan Token ID serta referensi mint unik. Sistem tidak membuat transaction hash blockchain palsu.

Konfigurasi opsional:

```env
BATIKCRAFT_MINT_NETWORK=BatikCraft Registry
BATIKCRAFT_MINT_CONTRACT_ADDRESS=
```

Provider blockchain publik dapat ditambahkan kemudian dengan mengganti implementasi mint setelah pembayaran, tanpa mengubah state invoice.

## Privasi bukti pembayaran

Bukti pembayaran disimpan melalui storage Django pada prefix `payment-proofs/`. File tidak ditautkan sebagai URL media publik. Endpoint bukti melakukan pemeriksaan bahwa peminta adalah creator transaksi, buyer transaksi, atau superuser.

Saat media lokal dipakai, jangan tambahkan `location /media/payment-proofs/` pada Nginx. Saat R2 dipakai, pertahankan bucket privat dan signed URL.

## Deployment VPS

Setelah branch/PR dipasang:

```bash
cd /srv/batikcraft
git pull
sudo docker compose -f docker-compose.mysql.yml up -d --build
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py migrate
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py check --database default
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py test core.test_auction_payment_flow
```

Periksa log:

```bash
sudo docker compose -f docker-compose.mysql.yml logs --tail=150 web
```

## Operasional

Creator harus memverifikasi dana pada rekening atau wallet di luar BatikCraft sebelum menekan **Pembayaran diterima & mint NFT**. Tombol tersebut bersifat final: NFT berubah menjadi `sold`, current owner menjadi buyer, dan registry mint dibuat.

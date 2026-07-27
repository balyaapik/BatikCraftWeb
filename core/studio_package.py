"""Verifikasi paket .batikcraftnft yang dihasilkan BatikCraft Studio.

Gambar NFT di marketplace wajib berasal dari paket Studio yang utuh. Modul ini
membuka paket, memeriksa manifest, seal, dan checksum setiap berkas, lalu
mengembalikan sidik jari preview sehingga pemanggil dapat memastikan gambar yang
diunggah benar-benar preview dari proyek di dalam paket.

Batas jaminan yang perlu diketahui: format paket ini memakai checksum, bukan
tanda tangan kunci publik — manifest Studio sendiri mencatat
``integrity.digital_signature = False``. Pemeriksaan di sini membuktikan paket
konsisten dan gambar cocok dengan isinya, bukan membuktikan paket dibuat oleh
salinan Studio yang sah. Untuk bukti asal usul yang sesungguhnya, paket perlu
ditandatangani dengan kunci privat yang tidak ikut didistribusikan bersama
aplikasi desktop.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass

MANIFEST_PATH = "manifest.json"
SEAL_PATH = "seal.json"
PREVIEW_PATH = "preview.jpg"
NFT_FORMAT = "batikcraft-nft"
SEAL_FORMAT = "batikcraft-nft-seal"

# Paket dengan banyak berkas kecil bisa dipakai untuk zip bomb; batasi jumlah
# entri dan total ukuran hasil dekompresi.
MAX_ENTRIES = 2000
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class StudioPackageError(Exception):
    """Paket tidak memenuhi syarat sebagai keluaran BatikCraft Studio."""


@dataclass(frozen=True)
class VerifiedStudioPackage:
    package_id: str
    project_id: str
    creator_user_id: str
    title: str
    preview_sha256: str
    preview_size: int


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_upload(upload) -> str:
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise StudioPackageError(f"Bagian '{label}' pada paket tidak valid.")
    return value


def _decode_json(raw: bytes, label: str) -> dict:
    try:
        return _mapping(json.loads(raw.decode("utf-8")), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudioPackageError(f"Berkas '{label}' bukan JSON yang valid.") from exc


def verify_studio_package(fileobj) -> VerifiedStudioPackage:
    """Buka dan validasi paket, lalu kembalikan identitas beserta sidik preview."""
    try:
        with zipfile.ZipFile(fileobj) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise StudioPackageError("Paket berisi terlalu banyak berkas.")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise StudioPackageError("Isi paket melebihi batas ukuran wajar.")

            by_path = {info.filename: info for info in infos}
            if MANIFEST_PATH not in by_path or SEAL_PATH not in by_path:
                raise StudioPackageError(
                    "Paket tidak memiliki manifest.json atau seal.json."
                )

            manifest_bytes = archive.read(by_path[MANIFEST_PATH])
            manifest = _decode_json(manifest_bytes, MANIFEST_PATH)
            seal = _decode_json(archive.read(by_path[SEAL_PATH]), SEAL_PATH)

            if manifest.get("format") != NFT_FORMAT:
                raise StudioPackageError(
                    "Paket bukan berformat batikcraft-nft dari BatikCraft Studio."
                )
            if seal.get("format") != SEAL_FORMAT:
                raise StudioPackageError("Seal paket tidak dikenali.")
            if seal.get("manifest_sha256") != sha256_of(manifest_bytes):
                raise StudioPackageError("Manifest paket sudah diubah setelah disegel.")
            if seal.get("package_id") != manifest.get("package_id"):
                raise StudioPackageError("Seal merujuk paket yang berbeda.")

            records = manifest.get("files")
            if not isinstance(records, list) or not records:
                raise StudioPackageError("Manifest tidak mendaftarkan berkas apa pun.")

            declared: dict[str, dict] = {}
            for record in records:
                entry = _mapping(record, "files")
                path = str(entry.get("path") or "")
                if not path:
                    raise StudioPackageError("Manifest memuat entri tanpa path.")
                declared[path] = entry

            actual = set(by_path) - {MANIFEST_PATH, SEAL_PATH}
            if actual != set(declared):
                raise StudioPackageError(
                    "Isi paket tidak cocok dengan daftar berkas di manifest."
                )

            preview_entry = declared.get(PREVIEW_PATH)
            if preview_entry is None:
                raise StudioPackageError("Paket tidak memuat preview.jpg.")

            for path, entry in declared.items():
                content = archive.read(by_path[path])
                if len(content) != int(entry.get("size") or -1):
                    raise StudioPackageError(f"Ukuran berkas berubah: {path}")
                if sha256_of(content) != str(entry.get("sha256") or ""):
                    raise StudioPackageError(f"Checksum berkas berubah: {path}")

            identity = _mapping(manifest.get("identity"), "identity")
            creator = _mapping(identity.get("creator"), "identity.creator")
            return VerifiedStudioPackage(
                package_id=str(manifest.get("package_id") or ""),
                project_id=str(identity.get("project_id") or ""),
                creator_user_id=str(creator.get("user_id") or ""),
                title=str(identity.get("title") or ""),
                preview_sha256=str(preview_entry.get("sha256") or ""),
                preview_size=int(preview_entry.get("size") or 0),
            )
    except zipfile.BadZipFile as exc:
        raise StudioPackageError("Paket bukan arsip yang dapat dibaca.") from exc

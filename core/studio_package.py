"""Verifikasi paket .batikcraftnft yang dihasilkan BatikCraft Studio.

Gambar NFT di marketplace wajib berasal dari paket Studio yang utuh. Modul ini
membuka paket, memeriksa manifest, seal, path, batas ukuran, dan checksum setiap
berkas. Untuk listing pustaka aset, envelope boleh memuat tepat satu
``.batikpack`` yang juga diverifikasi sebagai paket installable sebelum disimpan.

Batas jaminan yang perlu diketahui: format paket memakai checksum, bukan tanda
tangan kunci publik. Pemeriksaan membuktikan paket konsisten dan preview cocok
dengan isinya, tetapi belum membuktikan paket dibuat oleh salinan Studio yang
memegang identitas kriptografis tertentu.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

MANIFEST_PATH = "manifest.json"
SEAL_PATH = "seal.json"
PREVIEW_PATH = "preview.jpg"
NFT_FORMAT = "batikcraft-nft"
SEAL_FORMAT = "batikcraft-nft-seal"
ASSET_PACK_FORMAT = "batikcraft-asset-pack"
ASSET_PACK_SCHEMA_VERSION = "1.0"

# Batas outer envelope dan pustaka tertanam. Outer hanya memuat beberapa file,
# sedangkan .batikpack dapat memuat banyak asset dan thumbnail.
MAX_ENTRIES = 4096
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 768 * 1024 * 1024
MAX_ASSET_PACK_ENTRIES = 100_000
MAX_ASSET_PACK_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ASSET_PACK_BYTES = 512 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


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
    asset_pack_path: str = ""
    asset_pack_filename: str = ""
    asset_pack_sha256: str = ""
    asset_pack_size: int = 0
    asset_pack_id: str = ""
    asset_pack_name: str = ""


@dataclass(frozen=True)
class VerifiedAssetPack:
    pack_id: str
    name: str
    size: int
    sha256: str


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


def _safe_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise StudioPackageError(f"Path {label} tidak aman.")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise StudioPackageError(f"Path {label} tidak aman: {value!r}.")
    normalized = path.as_posix()
    if normalized != value or ":" in path.parts[0]:
        raise StudioPackageError(f"Path {label} tidak kanonik: {value!r}.")
    return normalized


def _validated_members(
    archive: zipfile.ZipFile,
    *,
    maximum_entries: int,
    maximum_member_bytes: int,
    maximum_total_bytes: int,
    label: str,
) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > maximum_entries:
        raise StudioPackageError(f"{label} berisi terlalu banyak berkas.")
    by_path: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        if info.is_dir():
            raise StudioPackageError(f"{label} tidak boleh memuat entri folder.")
        path = _safe_path(info.filename, label)
        key = path.casefold()
        if any(existing.casefold() == key for existing in by_path):
            raise StudioPackageError(f"Path ganda dalam {label}: {path!r}.")
        if info.flag_bits & 0x1:
            raise StudioPackageError(f"Berkas terenkripsi tidak didukung: {path!r}.")
        if info.file_size > maximum_member_bytes:
            raise StudioPackageError(f"Berkas terlalu besar dalam {label}: {path!r}.")
        total += info.file_size
        if total > maximum_total_bytes:
            raise StudioPackageError(f"Ukuran hasil dekompresi {label} melebihi batas.")
        by_path[path] = info
    return by_path


def verify_asset_pack_bytes(content: bytes) -> VerifiedAssetPack:
    """Pastikan payload tertanam benar-benar `.batikpack` yang installable."""
    if not isinstance(content, bytes) or not content:
        raise StudioPackageError("Pustaka aset tertanam kosong.")
    if len(content) > MAX_ASSET_PACK_BYTES:
        raise StudioPackageError("Pustaka aset tertanam melebihi batas ukuran.")

    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(content)) as archive:
            by_path = _validated_members(
                archive,
                maximum_entries=MAX_ASSET_PACK_ENTRIES,
                maximum_member_bytes=MAX_ASSET_PACK_MEMBER_BYTES,
                maximum_total_bytes=MAX_ASSET_PACK_BYTES,
                label="asset pack",
            )
            manifest_info = by_path.get(MANIFEST_PATH)
            if manifest_info is None:
                raise StudioPackageError("Asset pack tidak memiliki manifest.json di root.")
            manifest = _decode_json(archive.read(manifest_info), "asset pack manifest.json")
            if set(manifest) != {"format", "schema_version", "pack", "assets"}:
                raise StudioPackageError("Field root manifest asset pack tidak valid.")
            if manifest.get("format") != ASSET_PACK_FORMAT:
                raise StudioPackageError("Format asset pack tidak didukung.")
            if manifest.get("schema_version") != ASSET_PACK_SCHEMA_VERSION:
                raise StudioPackageError("Versi schema asset pack tidak didukung.")

            pack = _mapping(manifest.get("pack"), "asset pack.pack")
            pack_id = str(pack.get("id") or "")
            name = str(pack.get("name") or "").strip()
            version = str(pack.get("version") or "").strip()
            if not _IDENTIFIER_RE.fullmatch(pack_id):
                raise StudioPackageError("ID asset pack tidak valid.")
            if not name or len(name) > 160 or not version or len(version) > 40:
                raise StudioPackageError("Metadata asset pack tidak lengkap.")

            assets = manifest.get("assets")
            if not isinstance(assets, list) or not assets:
                raise StudioPackageError("Asset pack harus memuat sedikitnya satu asset.")
            declared_files = {MANIFEST_PATH}
            asset_ids: set[str] = set()
            for index, raw in enumerate(assets):
                item = _mapping(raw, f"asset pack.assets[{index}]")
                asset_id = str(item.get("id") or "")
                if not _IDENTIFIER_RE.fullmatch(asset_id) or asset_id in asset_ids:
                    raise StudioPackageError("ID asset dalam asset pack tidak valid atau ganda.")
                asset_ids.add(asset_id)
                asset_path = _safe_path(item.get("file"), "asset pack asset")
                if not asset_path.endswith(".batikasset"):
                    raise StudioPackageError("File asset wajib berakhiran .batikasset.")
                if asset_path in declared_files:
                    raise StudioPackageError("File asset ganda dalam manifest asset pack.")
                declared_files.add(asset_path)
                thumbnail = item.get("thumbnail")
                if thumbnail is not None:
                    thumbnail_path = _safe_path(thumbnail, "asset pack thumbnail")
                    if thumbnail_path in declared_files:
                        raise StudioPackageError("Thumbnail ganda dalam manifest asset pack.")
                    declared_files.add(thumbnail_path)

            if set(by_path) != declared_files:
                raise StudioPackageError(
                    "Isi asset pack tidak cocok dengan file yang dideklarasikan manifest."
                )
            return VerifiedAssetPack(
                pack_id=pack_id,
                name=name,
                size=len(content),
                sha256=sha256_of(content),
            )
    except StudioPackageError:
        raise
    except zipfile.BadZipFile as exc:
        raise StudioPackageError("Pustaka aset tertanam bukan arsip yang dapat dibaca.") from exc


def verify_studio_package(fileobj) -> VerifiedStudioPackage:
    """Buka dan validasi envelope, preview, dan `.batikpack` tertanam bila ada."""
    try:
        fileobj.seek(0)
        with zipfile.ZipFile(fileobj) as archive:
            by_path = _validated_members(
                archive,
                maximum_entries=MAX_ENTRIES,
                maximum_member_bytes=MAX_MEMBER_BYTES,
                maximum_total_bytes=MAX_UNCOMPRESSED_BYTES,
                label="paket NFT",
            )
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
                path = _safe_path(entry.get("path"), "manifest NFT")
                if path.casefold() in {item.casefold() for item in declared}:
                    raise StudioPackageError("Manifest memuat path file ganda.")
                try:
                    size = int(entry.get("size"))
                except (TypeError, ValueError) as exc:
                    raise StudioPackageError(f"Ukuran file tidak valid: {path}") from exc
                checksum = str(entry.get("sha256") or "")
                if size < 0 or not _SHA256_RE.fullmatch(checksum):
                    raise StudioPackageError(f"Record integritas tidak valid: {path}")
                declared[path] = {**entry, "size": size, "sha256": checksum}

            actual = set(by_path) - {MANIFEST_PATH, SEAL_PATH}
            if actual != set(declared):
                raise StudioPackageError(
                    "Isi paket tidak cocok dengan daftar berkas di manifest."
                )

            preview_entry = declared.get(PREVIEW_PATH)
            if preview_entry is None:
                raise StudioPackageError("Paket tidak memuat preview.jpg.")

            embedded: tuple[str, dict, VerifiedAssetPack] | None = None
            for path, entry in declared.items():
                content = archive.read(by_path[path])
                if len(content) != entry["size"]:
                    raise StudioPackageError(f"Ukuran berkas berubah: {path}")
                if sha256_of(content) != entry["sha256"]:
                    raise StudioPackageError(f"Checksum berkas berubah: {path}")
                if path.startswith("project/") and path.casefold().endswith(".batikpack"):
                    if embedded is not None:
                        raise StudioPackageError(
                            "Envelope pustaka hanya boleh memuat satu .batikpack."
                        )
                    embedded = (path, entry, verify_asset_pack_bytes(content))

            identity = _mapping(manifest.get("identity"), "identity")
            creator = _mapping(identity.get("creator"), "identity.creator")
            result = VerifiedStudioPackage(
                package_id=str(manifest.get("package_id") or ""),
                project_id=str(identity.get("project_id") or ""),
                creator_user_id=str(creator.get("user_id") or ""),
                title=str(identity.get("title") or ""),
                preview_sha256=str(preview_entry.get("sha256") or ""),
                preview_size=int(preview_entry.get("size") or 0),
            )
            if embedded is None:
                return result
            path, entry, asset_pack = embedded
            return VerifiedStudioPackage(
                **result.__dict__,
                asset_pack_path=path,
                asset_pack_filename=PurePosixPath(path).name,
                asset_pack_sha256=entry["sha256"],
                asset_pack_size=entry["size"],
                asset_pack_id=asset_pack.pack_id,
                asset_pack_name=asset_pack.name,
            )
    except StudioPackageError:
        raise
    except zipfile.BadZipFile as exc:
        raise StudioPackageError("Paket bukan arsip yang dapat dibaca.") from exc
    finally:
        try:
            fileobj.seek(0)
        except (AttributeError, OSError):
            pass


def read_embedded_asset_pack(fileobj, verified: VerifiedStudioPackage) -> bytes:
    """Ambil `.batikpack` dari envelope yang telah diverifikasi.

    Ukuran, checksum, dan struktur installable diperiksa ulang saat pembacaan agar
    byte yang disimpan tidak mungkin berbeda dari byte yang sebelumnya diverifikasi.
    """
    if not verified.asset_pack_path:
        raise StudioPackageError("Envelope tidak memuat pustaka aset.")
    try:
        fileobj.seek(0)
        with zipfile.ZipFile(fileobj) as archive:
            info = archive.getinfo(verified.asset_pack_path)
            if info.file_size != verified.asset_pack_size:
                raise StudioPackageError("Ukuran pustaka tertanam berubah.")
            content = archive.read(info)
        if sha256_of(content) != verified.asset_pack_sha256:
            raise StudioPackageError("Checksum pustaka tertanam berubah.")
        checked = verify_asset_pack_bytes(content)
        if checked.pack_id != verified.asset_pack_id:
            raise StudioPackageError("Identitas pustaka tertanam berubah.")
        return content
    except KeyError as exc:
        raise StudioPackageError("Pustaka tertanam tidak ditemukan dalam envelope.") from exc
    except zipfile.BadZipFile as exc:
        raise StudioPackageError("Envelope tidak dapat dibaca kembali.") from exc
    finally:
        try:
            fileobj.seek(0)
        except (AttributeError, OSError):
            pass

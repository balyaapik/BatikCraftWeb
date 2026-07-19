from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError

from storage_config.models import StorageConfiguration
from storage_config.services import build_r2_storage


class Command(BaseCommand):
    help = "Copy existing MEDIA_ROOT files to the Cloudflare R2 bucket configured in admin."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be copied without uploading files.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace an R2 object when the same key exists with a different size.",
        )
        parser.add_argument(
            "--delete-local",
            action="store_true",
            help="Delete each local file only after the R2 copy is verified.",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Only migrate media paths below this prefix, for example nfts/.",
        )

    def handle(self, *args, **options):
        try:
            configuration = StorageConfiguration.objects.get(singleton_id=1)
        except StorageConfiguration.DoesNotExist as exc:
            raise CommandError(
                "Konfigurasi R2 belum tersedia. Isi melalui dashboard administrator."
            ) from exc
        if not configuration.is_complete:
            raise CommandError("Konfigurasi R2 belum lengkap.")

        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            raise CommandError(f"Folder media lokal tidak ditemukan: {root}")

        local_storage = FileSystemStorage(location=root, base_url=settings.MEDIA_URL)
        remote_storage = build_r2_storage(configuration)
        prefix = options["prefix"].strip("/")
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]
        delete_local = options["delete_local"]

        names = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
        if prefix:
            names = [name for name in names if name == prefix or name.startswith(f"{prefix}/")]

        copied = 0
        skipped = 0
        conflicts = 0
        deleted = 0

        for name in names:
            local_size = local_storage.size(name)
            if remote_storage.exists(name):
                remote_size = remote_storage.size(name)
                if remote_size == local_size:
                    self.stdout.write(f"SKIP {name} ({local_size} bytes, already matches)")
                    skipped += 1
                    if delete_local and not dry_run:
                        local_storage.delete(name)
                        deleted += 1
                    continue
                if not overwrite:
                    self.stderr.write(
                        f"CONFLICT {name}: local={local_size}, r2={remote_size}; use --overwrite"
                    )
                    conflicts += 1
                    continue

            if dry_run:
                self.stdout.write(f"COPY {name} ({local_size} bytes)")
                copied += 1
                continue

            if overwrite and remote_storage.exists(name):
                remote_storage.delete(name)
            with local_storage.open(name, "rb") as source:
                saved_name = remote_storage.save(name, source)
            if saved_name != name:
                raise CommandError(
                    f"R2 mengubah object key {name!r} menjadi {saved_name!r}. Migrasi dihentikan."
                )
            if not remote_storage.exists(name) or remote_storage.size(name) != local_size:
                raise CommandError(f"Verifikasi R2 gagal untuk {name}.")

            copied += 1
            self.stdout.write(self.style.SUCCESS(f"COPIED {name}"))
            if delete_local:
                local_storage.delete(name)
                deleted += 1

        summary = (
            f"Selesai: copied={copied}, skipped={skipped}, "
            f"conflicts={conflicts}, deleted_local={deleted}."
        )
        if dry_run:
            summary = f"Dry-run. {summary}"
        self.stdout.write(self.style.SUCCESS(summary))
        if conflicts:
            raise CommandError(
                "Ada file konflik yang tidak disalin. Periksa hasil lalu jalankan dengan --overwrite bila sesuai."
            )

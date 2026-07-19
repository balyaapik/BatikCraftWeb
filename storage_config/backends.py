from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage
from django.db.utils import OperationalError, ProgrammingError

from .models import StorageConfiguration
from .services import build_r2_storage


class DynamicMediaStorage(Storage):
    """Use R2 when enabled in admin, otherwise keep using local VPS media."""

    def _local_storage(self) -> FileSystemStorage:
        return FileSystemStorage(
            location=settings.MEDIA_ROOT,
            base_url=settings.MEDIA_URL,
        )

    def _storage(self) -> Storage:
        try:
            configuration = StorageConfiguration.objects.filter(
                singleton_id=1,
                enabled=True,
            ).first()
        except (OperationalError, ProgrammingError):
            # The storage table may not exist yet while migrations are running.
            configuration = None
        if configuration is None:
            return self._local_storage()
        return build_r2_storage(configuration)

    def _open(self, name, mode="rb"):
        return self._storage().open(name, mode)

    def _save(self, name, content):
        return self._storage().save(name, content)

    def save(self, name, content, max_length=None):
        return self._storage().save(name, content, max_length=max_length)

    def delete(self, name):
        return self._storage().delete(name)

    def exists(self, name):
        return self._storage().exists(name)

    def listdir(self, path):
        return self._storage().listdir(path)

    def size(self, name):
        return self._storage().size(name)

    def url(self, name):
        return self._storage().url(name)

    def path(self, name):
        return self._storage().path(name)

    def get_available_name(self, name, max_length=None):
        return self._storage().get_available_name(name, max_length=max_length)

    def get_accessed_time(self, name):
        return self._storage().get_accessed_time(name)

    def get_created_time(self, name):
        return self._storage().get_created_time(name)

    def get_modified_time(self, name):
        return self._storage().get_modified_time(name)

"""
Local filesystem artifact storage wrapper.

Production would swap this for an S3-backed implementation without changing
any service code, since services depend only on ArtifactStorage.
"""

import os

from django.conf import settings


class ArtifactStorage:
    """
    Filesystem-backed artifact storage.

    Uses ARTIFACT_MEDIA_ROOT from settings as the root directory.
    The storage_key is used directly as a relative path under that root.
    """

    def _full_path(self, storage_key: str) -> str:
        return os.path.join(settings.ARTIFACT_MEDIA_ROOT, storage_key)

    def save(self, storage_key: str, file_obj) -> None:
        full_path = self._full_path(storage_key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        file_obj.seek(0)
        with open(full_path, "wb") as f:
            for chunk in file_obj.chunks():
                f.write(chunk)

    def open(self, storage_key: str):
        return open(self._full_path(storage_key), "rb")

    def exists(self, storage_key: str) -> bool:
        return os.path.exists(self._full_path(storage_key))

    def size(self, storage_key: str) -> int:
        return os.path.getsize(self._full_path(storage_key))

    def delete(self, storage_key: str) -> None:
        path = self._full_path(storage_key)
        if os.path.exists(path):
            os.remove(path)

    def local_path(self, storage_key: str) -> str:
        return self._full_path(storage_key)

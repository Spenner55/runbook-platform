"""
Local filesystem artifact storage wrapper.

Production would swap this for an S3-backed implementation without changing
any service code, since services depend only on ArtifactStorage.
"""

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation


class ArtifactStorage:
    """
    Filesystem-backed artifact storage.

    Uses ARTIFACT_MEDIA_ROOT from settings as the root directory.
    The storage_key is used directly as a relative path under that root.
    """

    def __init__(self) -> None:
        if settings.ARTIFACT_STORAGE_BACKEND != "local":
            raise ImproperlyConfigured(
                "Only local artifact storage is implemented in Phase 10.4. "
                "S3 settings are validated for production readiness, but the S3 backend "
                "is implemented in a later infrastructure phase."
            )

    def _full_path(self, storage_key: str) -> str:
        root = Path(settings.ARTIFACT_MEDIA_ROOT).resolve()
        full_path = (root / storage_key).resolve()
        if os.path.commonpath([str(root), str(full_path)]) != str(root):
            raise SuspiciousFileOperation("Artifact storage key escapes media root.")
        return str(full_path)

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

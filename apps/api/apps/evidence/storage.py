"""Evidence storage boundary.

Evidence packages intentionally use the existing artifact storage abstraction so
Phase 11.5 does not introduce a second storage backend.
"""

from django.core.files.base import ContentFile

from apps.artifacts.storage import ArtifactStorage


class EvidenceStorage:
    """Thin wrapper over ``ArtifactStorage`` for sealed evidence bytes."""

    def __init__(self, artifact_storage: ArtifactStorage | None = None) -> None:
        self._storage = artifact_storage or ArtifactStorage()

    def save_bytes(self, storage_key: str, content: bytes) -> None:
        self._storage.save(storage_key, ContentFile(content))

    def open(self, storage_key: str):
        return self._storage.open(storage_key)

    def read_bytes(self, storage_key: str) -> bytes:
        with self.open(storage_key) as file_obj:
            return file_obj.read()

    def exists(self, storage_key: str) -> bool:
        return self._storage.exists(storage_key)

    def size(self, storage_key: str) -> int:
        return self._storage.size(storage_key)

    def delete(self, storage_key: str) -> None:
        self._storage.delete(storage_key)

    def local_path(self, storage_key: str) -> str:
        return self._storage.local_path(storage_key)

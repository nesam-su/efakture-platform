from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import anyio
from fastapi import UploadFile

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    object_key: str
    size_bytes: int
    sha256: str


class LocalArtifactStore:
    """Filesystem-backed artifact store with tenant-scoped, non-guessable object keys."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def resolve(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Neispravan object key")
        return candidate

    async def put_upload(
        self, *, organization_id: uuid.UUID, document_id: uuid.UUID, upload: UploadFile
    ) -> StoredArtifact:
        original_name = Path(upload.filename or "artifact.bin").name
        safe_name = SAFE_FILENAME.sub("_", original_name).strip("._") or "artifact.bin"
        object_key = f"{organization_id}/{document_id}/{uuid.uuid4().hex}-{safe_name}"
        destination = self.resolve(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            async with await anyio.open_file(destination, "wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ArtifactTooLarge(
                            f"Prilog je veći od dozvoljenih {self.max_bytes} bajtova"
                        )
                    digest.update(chunk)
                    await output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return StoredArtifact(object_key, size, digest.hexdigest())

    async def read(self, object_key: str) -> bytes:
        async with await anyio.open_file(self.resolve(object_key), "rb") as source:
            return await source.read()

    def delete(self, object_key: str) -> None:
        self.resolve(object_key).unlink(missing_ok=True)

from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.storage import ArtifactTooLarge, LocalArtifactStore


def upload(name: str, content: bytes, content_type: str = "application/xml") -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_artifact_store_hashes_and_scopes_file(tmp_path):
    organization_id = uuid4()
    document_id = uuid4()
    store = LocalArtifactStore(tmp_path, max_bytes=1024)

    stored = await store.put_upload(
        organization_id=organization_id,
        document_id=document_id,
        upload=upload("../racun.xml", b"<Invoice/>"),
    )

    assert stored.object_key.startswith(f"{organization_id}/{document_id}/")
    assert ".." not in stored.object_key
    assert stored.size_bytes == len(b"<Invoice/>")
    assert len(stored.sha256) == 64
    assert await store.read(stored.object_key) == b"<Invoice/>"


@pytest.mark.asyncio
async def test_artifact_store_removes_oversized_partial_file(tmp_path):
    store = LocalArtifactStore(tmp_path, max_bytes=4)
    with pytest.raises(ArtifactTooLarge):
        await store.put_upload(
            organization_id=uuid4(),
            document_id=uuid4(),
            upload=upload("large.xml", b"12345"),
        )
    assert list(tmp_path.rglob("*.*")) == []

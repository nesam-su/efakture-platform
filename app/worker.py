from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db import SessionFactory
from app.integrations.eotpremnice import EotpremniceClient
from app.integrations.http import GovernmentApiError
from app.integrations.sef import SefClient
from app.models import (
    AuditEvent,
    BackgroundJob,
    BusinessDocument,
    DocumentArtifact,
    DocumentStatus,
    ExternalRequest,
    IntegrationCredential,
    JobStatus,
    Provider,
)
from app.storage import LocalArtifactStore
from app.synchronization import run_sync_cycle

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("efakture.worker")
settings = get_settings()
artifact_store = LocalArtifactStore(settings.artifact_storage_path, settings.max_artifact_bytes)
worker_id = f"{socket.gethostname()}:{os.getpid()}"


class PermanentJobError(RuntimeError):
    pass


async def claim_job() -> UUID | None:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=settings.worker_lock_timeout_seconds)
    async with SessionFactory() as db:
        job = await db.scalar(
            select(BackgroundJob)
            .where(
                or_(
                    (
                        BackgroundJob.status.in_([JobStatus.queued, JobStatus.retrying])
                        & (BackgroundJob.available_at <= now)
                    ),
                    (
                        (BackgroundJob.status == JobStatus.running)
                        & (BackgroundJob.locked_at < stale_before)
                    ),
                )
            )
            .order_by(BackgroundJob.available_at, BackgroundJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = JobStatus.running
        job.attempts += 1
        job.locked_at = now
        job.locked_by = worker_id
        await db.commit()
        return job.id


def _response_external_id(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in ("invoiceId", "documentId", "id"):
        value = response.get(key)
        if value is not None:
            return str(value)
    return None


async def _send_document(job_id: UUID) -> None:
    async with SessionFactory() as db:
        job = await db.get(BackgroundJob, job_id)
        if job is None:
            return
        document = await db.get(BusinessDocument, job.document_id)
        if document is None:
            raise PermanentJobError("Dokument više ne postoji")
        try:
            artifact_id = UUID(str(job.payload["artifact_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentJobError("Posao nema važeći artifact_id") from exc
        artifact = await db.scalar(
            select(DocumentArtifact).where(
                DocumentArtifact.id == artifact_id,
                DocumentArtifact.document_id == document.id,
                DocumentArtifact.organization_id == document.organization_id,
            )
        )
        if artifact is None:
            raise PermanentJobError("XML prilog nije pronađen")
        credential = await db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.organization_id == document.organization_id,
                IntegrationCredential.provider == document.provider,
                IntegrationCredential.is_active.is_(True),
            )
        )
        if credential is None:
            raise PermanentJobError("Aktivan API ključ za servis nije podešen")
        api_key = decrypt_secret(credential.encrypted_api_key)
        xml = await artifact_store.read(artifact.object_key)

        if document.provider == Provider.sef:
            async with SefClient(api_key=api_key, base_url=credential.base_url) as client:
                response = await client.send_sales_invoice(
                    xml,
                    request_id=document.idempotency_key,
                    send_to_cir=credential.settings.get("send_to_cir"),
                    execute_validation=credential.settings.get("execute_validation", True),
                )
            document.external_id = _response_external_id(response)
            document.remote_status = "Submitted"
        elif document.provider == Provider.eotpremnice:
            async with EotpremniceClient(api_key=api_key, base_url=credential.base_url) as client:
                response = await client.submit_document(
                    xml,
                    request_id=document.idempotency_key,
                    filename=artifact_store.resolve(artifact.object_key).name,
                )
            external_request = await db.scalar(
                select(ExternalRequest).where(
                    ExternalRequest.organization_id == document.organization_id,
                    ExternalRequest.provider == Provider.eotpremnice,
                    ExternalRequest.request_id == document.idempotency_key,
                )
            )
            if external_request is None:
                external_request = ExternalRequest(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    provider=Provider.eotpremnice,
                    request_id=document.idempotency_key,
                )
                db.add(external_request)
            external_request.status = "Submitted"
            external_request.response_payload = (
                response if isinstance(response, dict) else {"response": str(response)}
            )
            document.remote_status = "RequestSubmitted"
        else:
            raise PermanentJobError(f"Nepodržan servis: {document.provider}")

        now = datetime.now(UTC)
        document.status = DocumentStatus.sent
        document.remote_status_at = now
        document.last_error = None
        job.status = JobStatus.succeeded
        job.finished_at = now
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
        db.add(
            AuditEvent(
                organization_id=document.organization_id,
                action="document.send.succeeded",
                entity_type="business_document",
                entity_id=str(document.id),
                details={"provider": document.provider.value, "job_id": str(job.id)},
            )
        )
        await db.commit()


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(exc, GovernmentApiError) and (
        exc.status_code == 429 or exc.status_code >= 500
    )


async def fail_job(job_id: UUID, exc: Exception) -> None:
    async with SessionFactory() as db:
        job = await db.get(BackgroundJob, job_id)
        if job is None:
            return
        document = await db.get(BusinessDocument, job.document_id)
        message = str(exc)[:4000]
        retry = not isinstance(exc, PermanentJobError) and _is_transient(exc)
        now = datetime.now(UTC)
        if retry and job.attempts < job.max_attempts:
            delay_seconds = min(300, 5 * (2 ** max(0, job.attempts - 1)))
            job.status = JobStatus.retrying
            job.available_at = now + timedelta(seconds=delay_seconds)
            if document is not None:
                document.status = DocumentStatus.queued
        else:
            job.status = JobStatus.failed
            job.finished_at = now
            if document is not None:
                document.status = DocumentStatus.error
                document.last_error = message
        job.last_error = message
        job.locked_at = None
        job.locked_by = None
        db.add(
            AuditEvent(
                organization_id=job.organization_id,
                action="document.send.retry"
                if job.status == JobStatus.retrying
                else "document.send.failed",
                entity_type="background_job",
                entity_id=str(job.id),
                details={"attempt": job.attempts, "error_type": type(exc).__name__},
            )
        )
        await db.commit()


async def process_job(job_id: UUID) -> None:
    try:
        await _send_document(job_id)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        await fail_job(job_id, exc)


async def run_jobs() -> None:
    logger.info("Worker %s started", worker_id)
    while True:
        job_id = await claim_job()
        if job_id is None:
            await asyncio.sleep(settings.worker_poll_seconds)
            continue
        await process_job(job_id)


async def run_synchronization() -> None:
    while True:
        imported = await run_sync_cycle()
        if imported:
            logger.info("Imported %s new external events", imported)
        await asyncio.sleep(settings.sync_interval_seconds)


async def run() -> None:
    await asyncio.gather(run_jobs(), run_synchronization())


if __name__ == "__main__":
    asyncio.run(run())

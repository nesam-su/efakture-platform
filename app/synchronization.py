from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db import SessionFactory
from app.integrations.eotpremnice import EotpremniceClient
from app.integrations.eotpremnice import Role as EotRole
from app.integrations.sef import SefClient
from app.models import (
    BusinessDocument,
    Direction,
    DocumentArtifact,
    DocumentStatus,
    ExternalEvent,
    ExternalRequest,
    IntegrationCredential,
    Provider,
    SyncCursor,
)
from app.storage import LocalArtifactStore

logger = logging.getLogger("efakture.sync")
settings = get_settings()
artifact_store = LocalArtifactStore(settings.artifact_storage_path, settings.max_artifact_bytes)
SERBIA = ZoneInfo("Europe/Belgrade")
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"


def parse_event_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def sef_event_value(event: dict[str, Any], name: str) -> Any:
    """Read SEF fields from either documented camelCase or live PascalCase payloads."""
    if name in event:
        return event[name]
    folded_name = name.casefold()
    return next((value for key, value in event.items() if key.casefold() == folded_name), None)


def parse_sef_invoice_xml(
    content: bytes, direction: Literal["sales", "purchase"]
) -> dict[str, Any]:
    """Extract the list fields users need from a downloaded UBL invoice."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}
    if root.tag != f"{{{INVOICE}}}Invoice":
        embedded_invoice = root.find(f".//{{{INVOICE}}}Invoice")
        if embedded_invoice is None:
            return {}
        root = embedded_invoice

    def text(path: str) -> str | None:
        value = root.findtext(path, namespaces={"cbc": CBC, "cac": CAC})
        return value.strip() if value and value.strip() else None

    party = "AccountingCustomerParty" if direction == "sales" else "AccountingSupplierParty"
    party_path = f"./cac:{party}/cac:Party"
    name = text(f"{party_path}/cac:PartyLegalEntity/cbc:RegistrationName") or text(
        f"{party_path}/cac:PartyName/cbc:Name"
    )
    tax_id = text(f"{party_path}/cac:PartyTaxScheme/cbc:CompanyID") or text(
        f"{party_path}/cbc:EndpointID"
    )
    if tax_id and tax_id.upper().startswith("RS") and tax_id[2:].isdigit():
        tax_id = tax_id[2:]

    issue_date = None
    raw_issue_date = text("./cbc:IssueDate")
    if raw_issue_date:
        with suppress(ValueError):
            issue_date = datetime.combine(
                date.fromisoformat(raw_issue_date), time.min, tzinfo=SERBIA
            ).astimezone(UTC)

    payable = root.find(
        "./cac:LegalMonetaryTotal/cbc:PayableAmount", {"cbc": CBC, "cac": CAC}
    )
    raw_total = payable.text.strip() if payable is not None and payable.text else None
    try:
        total_amount = Decimal(raw_total) if raw_total else None
    except InvalidOperation:
        total_amount = None
    currency = text("./cbc:DocumentCurrencyCode")
    if not currency and payable is not None:
        currency = payable.attrib.get("currencyID")

    document_number = text("./cbc:ID")
    return {
        "document_number": document_number[:100] if document_number else None,
        "issue_date": issue_date,
        "counterparty_name": name[:300] if name else None,
        "counterparty_tax_id": tax_id[:20] if tax_id else None,
        "currency": currency[:3] if currency else None,
        "total_amount": total_amount,
    }


def sef_sync_date(
    watermark: datetime | None, *, today: date, initial_lookback_days: int
) -> date:
    """Choose a past calendar date accepted by the SEF changes endpoints."""
    latest_allowed = today - timedelta(days=1)
    if watermark is not None:
        candidate = watermark.astimezone(SERBIA).date()
    else:
        candidate = today - timedelta(days=min(max(initial_lookback_days, 1), 30))
    return min(candidate, latest_allowed)


def internal_status(remote_status: str | None) -> DocumentStatus:
    value = (remote_status or "").lower()
    if value in {"approved", "accepted", "fulfilled", "paid"}:
        return DocumentStatus.accepted
    if value in {"rejected"}:
        return DocumentStatus.rejected
    if value in {"cancelled", "canceled", "storno", "deleted"}:
        return DocumentStatus.cancelled
    if value in {"mistake", "failed", "error"}:
        return DocumentStatus.error
    if value in {
        "sent",
        "received",
        "delivered",
        "deliveryconfirmed",
        "transportationstarted",
        "seen",
        "renotified",
        "success",
    }:
        return DocumentStatus.delivered
    return DocumentStatus.sent


def request_status(current: str, incoming: str) -> str:
    """Keep an asynchronous failure terminal when older pending events arrive later."""
    if current == "Failed" and incoming in {"Pending", "Submitted"}:
        return current
    return incoming


def eot_document_refs(role: EotRole, event: dict[str, Any]) -> list[dict[str, Any]]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    directions: dict[EotRole, dict[str, Direction]] = {
        "suppliers": {
            "despatchAdvice": Direction.outbound,
            "receiptAdvice": Direction.inbound,
        },
        "customers": {
            "despatchAdvice": Direction.inbound,
            "receiptAdvice": Direction.outbound,
        },
        "carriers": {"despatchAdvice": Direction.inbound},
    }
    result = []
    for key, direction in directions[role].items():
        value = data.get(key)
        if not isinstance(value, dict) or not value.get("id"):
            continue
        result.append(
            {
                "external_id": str(value["id"]),
                "document_type": "despatch_advice" if key == "despatchAdvice" else "receipt_advice",
                "document_kind": "despatch-advices"
                if key == "despatchAdvice"
                else "receipt-advices",
                "document_number": value.get("documentNumber"),
                "remote_status": value.get("status"),
                "direction": direction,
            }
        )
    return result


async def _cursor(
    db: AsyncSession, *, organization_id: UUID, provider: Provider, stream: str
) -> SyncCursor:
    cursor = await db.scalar(
        select(SyncCursor).where(
            SyncCursor.organization_id == organization_id,
            SyncCursor.provider == provider,
            SyncCursor.stream == stream,
        )
    )
    if cursor is None:
        cursor = SyncCursor(
            organization_id=organization_id,
            provider=provider,
            stream=stream,
            cursor_data={},
        )
        db.add(cursor)
        await db.flush()
    return cursor


async def _record_event(
    db: AsyncSession,
    *,
    organization_id: UUID,
    provider: Provider,
    stream: str,
    external_event_id: str,
    event_type: str,
    occurred_at: datetime | None,
    request_id: str | None,
    data: dict[str, Any],
) -> bool:
    exists = await db.scalar(
        select(ExternalEvent.id).where(
            ExternalEvent.organization_id == organization_id,
            ExternalEvent.provider == provider,
            ExternalEvent.stream == stream,
            ExternalEvent.external_event_id == external_event_id,
        )
    )
    if exists is not None:
        return False
    db.add(
        ExternalEvent(
            organization_id=organization_id,
            provider=provider,
            stream=stream,
            external_event_id=external_event_id,
            event_type=event_type[:160],
            occurred_at=occurred_at,
            request_id=request_id,
            data=data,
        )
    )
    return True


async def _upsert_document(
    db: AsyncSession,
    *,
    organization_id: UUID,
    provider: Provider,
    external_id: str,
    direction: Direction,
    document_type: str,
    document_number: str | None,
    remote_status: str | None,
    event_time: datetime | None,
    payload: dict[str, Any],
) -> tuple[BusinessDocument, bool]:
    document = await db.scalar(
        select(BusinessDocument).where(
            BusinessDocument.organization_id == organization_id,
            BusinessDocument.provider == provider,
            BusinessDocument.external_id == external_id,
        )
    )
    created = document is None
    if document is None:
        document = BusinessDocument(
            organization_id=organization_id,
            provider=provider,
            direction=direction,
            document_type=document_type,
            document_number=document_number,
            external_id=external_id,
            idempotency_key=f"sync:{document_type}:{external_id}"[:128],
            payload=payload,
            status=DocumentStatus.sent,
        )
        db.add(document)
        await db.flush()
    else:
        document.document_number = document_number or document.document_number
        document.payload = payload
    if remote_status:
        document.remote_status = remote_status
        document.remote_status_at = event_time or datetime.now(UTC)
        document.status = internal_status(remote_status)
    return document, created


async def _store_remote_xml(
    db: AsyncSession,
    *,
    document: BusinessDocument,
    filename: str,
    content: bytes,
) -> None:
    checksum = hashlib.sha256(content).hexdigest()
    exists = await db.scalar(
        select(DocumentArtifact.id).where(
            DocumentArtifact.document_id == document.id,
            DocumentArtifact.sha256 == checksum,
        )
    )
    if exists is not None:
        return
    stored = await artifact_store.put_bytes(
        organization_id=document.organization_id,
        document_id=document.id,
        filename=filename,
        content=content,
    )
    db.add(
        DocumentArtifact(
            organization_id=document.organization_id,
            document_id=document.id,
            kind="remote_xml",
            object_key=stored.object_key,
            content_type="application/xml",
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
    )


async def sync_sef_stream(credential_id: UUID, direction: Literal["sales", "purchase"]) -> int:
    stream = f"sef:{direction}"
    async with SessionFactory() as db:
        credential = await db.get(IntegrationCredential, credential_id)
        if credential is None or not credential.is_active:
            return 0
        cursor = await _cursor(
            db,
            organization_id=credential.organization_id,
            provider=Provider.sef,
            stream=stream,
        )
        today = datetime.now(SERBIA).date()
        sync_date = sef_sync_date(
            cursor.watermark,
            today=today,
            initial_lookback_days=settings.sync_initial_lookback_days,
        )
        async with SefClient(
            api_key=decrypt_secret(credential.encrypted_api_key), base_url=credential.base_url
        ) as client:
            changes = await client.invoice_changes(direction, sync_date)
            imported = 0
            for event in changes:
                event_id = str(sef_event_value(event, "eventId") or "")
                invoice_key = "salesInvoiceId" if direction == "sales" else "purchaseInvoiceId"
                invoice_id = sef_event_value(event, invoice_key)
                if not event_id or invoice_id is None:
                    continue
                remote_status = sef_event_value(event, "newInvoiceStatus")
                event_time = parse_event_datetime(sef_event_value(event, "date"))
                is_new = await _record_event(
                    db,
                    organization_id=credential.organization_id,
                    provider=Provider.sef,
                    stream=stream,
                    external_event_id=event_id,
                    event_type=str(remote_status or "Unknown"),
                    occurred_at=event_time,
                    request_id=None,
                    data=event,
                )
                document, created = await _upsert_document(
                    db,
                    organization_id=credential.organization_id,
                    provider=Provider.sef,
                    external_id=str(invoice_id),
                    direction=Direction.outbound if direction == "sales" else Direction.inbound,
                    document_type="sales_invoice" if direction == "sales" else "purchase_invoice",
                    document_number=None,
                    remote_status=remote_status,
                    event_time=event_time,
                    payload=event,
                )
                if created or not document.document_number:
                    xml = await client.invoice_xml(direction, int(invoice_id))
                    summary = parse_sef_invoice_xml(xml, direction)
                    document.document_number = (
                        summary.get("document_number") or document.document_number
                    )
                    document.issue_date = summary.get("issue_date") or document.issue_date
                    document.counterparty_name = (
                        summary.get("counterparty_name") or document.counterparty_name
                    )
                    document.counterparty_tax_id = (
                        summary.get("counterparty_tax_id") or document.counterparty_tax_id
                    )
                    document.currency = summary.get("currency") or document.currency
                    if summary.get("total_amount") is not None:
                        document.total_amount = summary["total_amount"]
                    await _store_remote_xml(
                        db,
                        document=document,
                        filename=f"sef-{direction}-{invoice_id}.xml",
                        content=xml,
                    )
                imported += int(is_new)
        next_date = sync_date + timedelta(days=1)
        cursor.watermark = datetime.combine(next_date, time.min, tzinfo=SERBIA).astimezone(UTC)
        cursor.page = 0
        await db.commit()
        return imported


async def _handle_request_event(
    db: AsyncSession, *, organization_id: UUID, event: dict[str, Any]
) -> None:
    request_id = event.get("requestId")
    if not request_id:
        return
    request = await db.scalar(
        select(ExternalRequest).where(
            ExternalRequest.organization_id == organization_id,
            ExternalRequest.provider == Provider.eotpremnice,
            ExternalRequest.request_id == str(request_id),
        )
    )
    if request is None:
        return
    event_type = str(event.get("type") or "")
    incoming_status = event_type.rsplit(".", 1)[-1] or "Unknown"
    next_status = request_status(request.status, incoming_status)
    if next_status == "Failed" and incoming_status != "Failed":
        return
    request.status = next_status
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    request.response_payload = event
    messages = data.get("businessMessages") or event.get("businessMessages")
    if isinstance(messages, list):
        request.business_messages = messages
    document = await db.get(BusinessDocument, request.document_id) if request.document_id else None
    if document is not None:
        newer_request_id = await db.scalar(
            select(ExternalRequest.id)
            .where(
                ExternalRequest.organization_id == organization_id,
                ExternalRequest.provider == Provider.eotpremnice,
                ExternalRequest.document_id == document.id,
                ExternalRequest.created_at > request.created_at,
            )
            .order_by(ExternalRequest.created_at.desc())
            .limit(1)
        )
        if newer_request_id is not None:
            return
        document_id = data.get("documentId") or data.get("id")
        if document_id:
            document.external_id = str(document_id)
        document.remote_status = request.status
        document.remote_status_at = parse_event_datetime(event.get("date")) or datetime.now(UTC)
        document.status = internal_status(
            request.status if request.status == "Failed" else data.get("status") or request.status
        )
        if request.status == "Failed":
            document.last_error = str(messages or data)[:4000]


async def sync_eot_stream(credential_id: UUID, role: EotRole | None) -> int:
    stream = f"eotpremnice:{role or 'requests'}"
    async with SessionFactory() as db:
        credential = await db.get(IntegrationCredential, credential_id)
        if credential is None or not credential.is_active:
            return 0
        cursor = await _cursor(
            db,
            organization_id=credential.organization_id,
            provider=Provider.eotpremnice,
            stream=stream,
        )
        today = datetime.now(SERBIA).date()
        sync_date = (
            cursor.watermark.date()
            if cursor.watermark
            else today - timedelta(days=settings.sync_initial_lookback_days)
        )
        page = cursor.page
        async with EotpremniceClient(
            api_key=decrypt_secret(credential.encrypted_api_key), base_url=credential.base_url
        ) as client:
            response = (
                await client.role_changes(role, sync_date, page=page)
                if role
                else await client.request_changes(sync_date, page=page)
            )
            items = response.get("items", []) if isinstance(response, dict) else []
            imported = 0
            for event in items:
                if not isinstance(event, dict) or not event.get("id"):
                    continue
                is_new = await _record_event(
                    db,
                    organization_id=credential.organization_id,
                    provider=Provider.eotpremnice,
                    stream=stream,
                    external_event_id=str(event["id"]),
                    event_type=str(event.get("type") or "Unknown"),
                    occurred_at=parse_event_datetime(event.get("date")),
                    request_id=str(event["requestId"]) if event.get("requestId") else None,
                    data=event,
                )
                if role is None:
                    await _handle_request_event(
                        db, organization_id=credential.organization_id, event=event
                    )
                else:
                    for ref in eot_document_refs(role, event):
                        document, created = await _upsert_document(
                            db,
                            organization_id=credential.organization_id,
                            provider=Provider.eotpremnice,
                            external_id=ref["external_id"],
                            direction=ref["direction"],
                            document_type=ref["document_type"],
                            document_number=ref["document_number"],
                            remote_status=ref["remote_status"],
                            event_time=parse_event_datetime(event.get("date")),
                            payload=event,
                        )
                        if created:
                            xml = await client.download_artifact(
                                role,
                                ref["document_kind"],
                                ref["external_id"],
                                "xml",
                            )
                            await _store_remote_xml(
                                db,
                                document=document,
                                filename=f"eot-{ref['document_type']}-{ref['external_id']}.xml",
                                content=xml,
                            )
                imported += int(is_new)

        total = int(response.get("totalCount", len(items))) if isinstance(response, dict) else 0
        processed = int(cursor.cursor_data.get("processed", 0)) + len(items)
        if items and processed < total:
            cursor.page = page + 1
            cursor.cursor_data = {"processed": processed}
        elif sync_date < today:
            next_date = sync_date + timedelta(days=1)
            cursor.watermark = datetime.combine(next_date, time.min, tzinfo=UTC)
            cursor.page = 0
            cursor.cursor_data = {}
        else:
            cursor.watermark = datetime.combine(today, time.min, tzinfo=UTC)
            cursor.page = 0
            cursor.cursor_data = {}
        await db.commit()
        return imported


async def active_credential_ids() -> AsyncIterator[tuple[UUID, Provider]]:
    async with SessionFactory() as db:
        rows = (
            await db.execute(
                select(IntegrationCredential.id, IntegrationCredential.provider).where(
                    IntegrationCredential.is_active.is_(True)
                )
            )
        ).all()
    for row in rows:
        yield row.id, row.provider


async def run_sync_cycle() -> int:
    imported = 0
    async for credential_id, provider in active_credential_ids():
        if provider == Provider.sef:
            for direction in ("sales", "purchase"):
                try:
                    imported += await sync_sef_stream(credential_id, direction)
                except Exception:
                    logger.exception(
                        "Synchronization failed for credential %s stream sef:%s",
                        credential_id,
                        direction,
                    )
        else:
            for role in (None, "suppliers", "customers", "carriers"):
                try:
                    imported += await sync_eot_stream(credential_id, role)
                except Exception:
                    logger.exception(
                        "Synchronization failed for credential %s stream eotpremnice:%s",
                        credential_id,
                        role or "requests",
                    )
    return imported

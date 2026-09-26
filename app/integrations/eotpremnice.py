from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import uuid4

import httpx

from app.integrations.http import ApiKeyClient, json_or_text

EOTPREMNICE_DEMO_URL = "https://api.demoeotpremnica.mfin.gov.rs"
EOTPREMNICE_PRODUCTION_URL = "https://api.eotpremnica.mfin.gov.rs"
EOTPREMNICE_OFFLINE_DEMO_URL = "https://offline.demoeotpremnica.mfin.gov.rs"
EOTPREMNICE_OFFLINE_PRODUCTION_URL = "https://offline.eotpremnica.mfin.gov.rs"
EOTPREMNICE_API_CONTRACT_VERSION = "1.6.0"
EOTPREMNICE_DEMO_RELEASE = "1.6.3"
EOTPREMNICE_PRODUCTION_RELEASE = "1.6.1"

Role = Literal["suppliers", "customers", "carriers"]
DocumentKind = Literal["despatch-advices", "receipt-advices"]
ArtifactKind = Literal["xml", "pdf", "signature", "qr"]


def new_request_id() -> str:
    """Return a fresh identifier for one logical eOtpremnice submission."""
    return str(uuid4())


class EotpremniceClient(ApiKeyClient):
    """Sistem eOtpremnica API 1.6.0 client using UBL 1.1.0 examples."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = EOTPREMNICE_PRODUCTION_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            header_name="Api-key",
            transport=transport,
        )

    async def submit_document(
        self, xml: str | bytes, *, request_id: str, filename: str = "document.xml"
    ) -> Any:
        content = xml.encode() if isinstance(xml, str) else xml
        response = await self._request(
            "POST",
            "/public/documents/requests",
            data={"RequestId": request_id},
            files={"File": (filename, content, "text/xml")},
            headers={"Accept": "application/json"},
        )
        return json_or_text(response)

    async def request_changes(
        self, changed_on: date, *, page: int = 0, request_id: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"date": changed_on.isoformat(), "page": page}
        if request_id:
            params["requestId"] = request_id
        response = await self._request("GET", "/public/documents/requests/changes", params=params)
        return response.json()

    async def role_changes(
        self,
        role: Role,
        changed_on: date,
        *,
        page: int = 0,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"date": changed_on.isoformat(), "page": page}
        if request_id:
            params["requestId"] = request_id
        response = await self._request(
            "GET",
            f"/public/documents/{role}/changes",
            params=params,
        )
        return response.json()

    async def document_status(
        self, role: Role, document_kind: DocumentKind, document_id: str
    ) -> dict[str, Any]:
        response = await self._request(
            "GET", f"/public/documents/{role}/{document_kind}/{document_id}"
        )
        return response.json()

    async def download_artifact(
        self,
        role: Role,
        document_kind: DocumentKind,
        document_id: str,
        artifact: ArtifactKind,
    ) -> bytes:
        response = await self._request(
            "GET",
            f"/public/documents/{role}/{document_kind}/{document_id}/{artifact}/download",
        )
        return response.content

    async def download_application_response(self, role: Role, document_id: str) -> bytes:
        """Download the documented ApplicationResponse XML for a tenant role."""
        response = await self._request(
            "GET",
            f"/public/documents/{role}/application-responses/{document_id}/xml/download",
        )
        return response.content

    async def subscribe_webhook(self) -> Any:
        response = await self._request("POST", "/public/webhook-notifications/subscribe")
        return json_or_text(response)

    async def validate_document(self, xml: str | bytes, *, filename: str = "document.xml") -> Any:
        content = xml.encode() if isinstance(xml, str) else xml
        response = await self._request(
            "POST",
            "/public/xml-validator/validate-document",
            files={"File": (filename, content, "text/xml")},
        )
        return json_or_text(response)

    async def company_status(self, *, vat_identifier: str, jbkjs: str | None = None) -> Any:
        params = {"VatIdentifier": vat_identifier}
        if jbkjs:
            params["Jbkjs"] = jbkjs
        response = await self._request("GET", "/public/companies/status", params=params)
        return json_or_text(response)


class EotpremniceOfflineClient(ApiKeyClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = EOTPREMNICE_OFFLINE_PRODUCTION_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            header_name="Api-key",
            transport=transport,
        )

    async def upload_pdf(self, pdf: bytes, *, filename: str = "offline-document.pdf") -> Any:
        response = await self._request(
            "POST",
            "/public/offline",
            files={"file": (filename, pdf, "application/pdf")},
        )
        return json_or_text(response)

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

import httpx

from app.integrations.http import ApiKeyClient, json_or_text

SEF_DEMO_URL = "https://demoefaktura.mfin.gov.rs"
SEF_PRODUCTION_URL = "https://efaktura.mfin.gov.rs"


class SefClient(ApiKeyClient):
    """SEF Public API v1/v2 client, mapped from the supplied 31 July 2026 contract."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = SEF_PRODUCTION_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            header_name="ApiKey",
            transport=transport,
        )

    async def version(self) -> Any:
        response = await self._request("GET", "/api/publicApi/getEfakturaVersion")
        return json_or_text(response)

    async def send_sales_invoice(
        self,
        xml: str | bytes,
        *,
        request_id: str,
        send_to_cir: str | None = None,
        execute_validation: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, str | bool] = {
            "requestId": request_id,
            "executeValidation": execute_validation,
        }
        if send_to_cir is not None:
            params["sendToCir"] = send_to_cir
        response = await self._request(
            "POST",
            "/api/publicApi/sales-invoice/ubl",
            params=params,
            content=xml.encode() if isinstance(xml, str) else xml,
            headers={"Content-Type": "application/xml", "Accept": "application/json"},
        )
        return response.json()

    async def invoice_changes(
        self,
        direction: Literal["sales", "purchase"],
        changed_at: datetime,
    ) -> list[dict[str, Any]]:
        path = f"/api/publicApi/{direction}-invoice/changes"
        response = await self._request("POST", path, params={"date": changed_at.isoformat()})
        return response.json()

    async def invoice_xml(self, direction: Literal["sales", "purchase"], invoice_id: int) -> bytes:
        path = f"/api/publicApi/{direction}-invoice/xml"
        response = await self._request("GET", path, params={"invoiceId": invoice_id})
        return response.content

    async def invoice_pdf(self, direction: Literal["sales", "purchase"], invoice_id: int) -> bytes:
        path = f"/api/publicApi/{direction}-invoice/pdf"
        response = await self._request("GET", path, params={"invoiceId": invoice_id})
        return response.content

    async def accept_or_reject_purchase_invoice(
        self, invoice_id: int, *, accepted: bool, comment: str | None = None
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/api/publicApi/purchase-invoice/acceptRejectPurchaseInvoice",
            json={"invoiceId": invoice_id, "accepted": accepted, "comment": comment},
        )
        return response.json()

    async def subscribe_for_next_day(self) -> Any:
        response = await self._request("POST", "/api/publicApi/subscribe")
        return json_or_text(response)

    async def group_vat_changes(self, changed_on: date) -> Any:
        response = await self._request(
            "GET", "/api/v2/publicApi/vat-recording/group", params={"date": changed_on.isoformat()}
        )
        return json_or_text(response)

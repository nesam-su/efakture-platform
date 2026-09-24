from datetime import UTC, date, datetime

import httpx
import pytest

from app.integrations.environments import integration_base_url
from app.integrations.eotpremnice import EotpremniceClient
from app.integrations.sef import SefClient
from app.models import Provider


def test_official_demo_and_production_endpoints_are_fixed():
    assert integration_base_url(Provider.sef, "demo") == "https://demoefaktura.mfin.gov.rs"
    assert integration_base_url(Provider.sef, "production") == "https://efaktura.mfin.gov.rs"
    assert integration_base_url(Provider.eotpremnice, "demo") == (
        "https://api.demoeotpremnica.mfin.gov.rs"
    )
    assert integration_base_url(Provider.eotpremnice, "production") == (
        "https://api.eotpremnica.mfin.gov.rs"
    )


@pytest.mark.asyncio
async def test_sef_invoice_upload_uses_documented_contract():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/publicApi/sales-invoice/ubl"
        assert request.headers["ApiKey"] == "secret"
        assert request.headers["Content-Type"] == "application/xml"
        assert request.url.params["requestId"] == "INV-2026-001"
        assert request.url.params["executeValidation"] == "true"
        assert await request.aread() == b"<Invoice/>"
        return httpx.Response(200, json={"invoiceId": 42})

    client = SefClient(
        api_key="secret", base_url="https://sef.test", transport=httpx.MockTransport(handler)
    )
    try:
        result = await client.send_sales_invoice("<Invoice/>", request_id="INV-2026-001")
    finally:
        await client.aclose()
    assert result == {"invoiceId": 42}


@pytest.mark.asyncio
async def test_eotpremnice_submit_and_pull_contract():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Api-key"] == "secret"
        if request.method == "POST":
            body = await request.aread()
            assert request.url.path == "/public/documents/requests"
            assert b"RequestId" in body and b"REQ-2026-001" in body
            assert b"<DespatchAdvice/>" in body
            return httpx.Response(202, json={"accepted": True})
        if request.url.path == "/public/documents/customers/changes":
            assert request.url.params["requestId"] == "REQ-2026-001"
            return httpx.Response(200, json={"items": [], "totalCount": 0, "pageIndex": 0})
        assert request.url.path == "/public/documents/requests/changes"
        assert request.url.params["date"] == "2026-09-23"
        assert request.url.params["page"] == "0"
        return httpx.Response(200, json={"items": [], "totalCount": 0, "pageIndex": 0})

    client = EotpremniceClient(
        api_key="secret", base_url="https://eo.test", transport=httpx.MockTransport(handler)
    )
    try:
        await client.submit_document("<DespatchAdvice/>", request_id="REQ-2026-001")
        changes = await client.request_changes(date(2026, 9, 23))
        await client.role_changes("customers", date(2026, 9, 23), request_id="REQ-2026-001")
    finally:
        await client.aclose()
    assert len(calls) == 3
    assert changes["totalCount"] == 0


@pytest.mark.asyncio
async def test_sef_change_date_keeps_time_and_timezone():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["date"] == "2026-09-23T10:11:12+00:00"
        return httpx.Response(200, json=[])

    client = SefClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        result = await client.invoice_changes(
            "purchase", datetime(2026, 9, 23, 10, 11, 12, tzinfo=UTC)
        )
    finally:
        await client.aclose()
    assert result == []


@pytest.mark.asyncio
async def test_eotpremnice_application_response_uses_plural_official_path():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/public/documents/customers/application-responses/response-42/xml/download"
        )
        return httpx.Response(200, content=b"<ApplicationResponse/>")

    client = EotpremniceClient(
        api_key="secret", base_url="https://eo.test", transport=httpx.MockTransport(handler)
    )
    try:
        content = await client.download_application_response("customers", "response-42")
    finally:
        await client.aclose()
    assert content == b"<ApplicationResponse/>"

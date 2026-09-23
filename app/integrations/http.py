from __future__ import annotations

from typing import Any

import httpx


class GovernmentApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.trace_id = trace_id


class ApiKeyClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        header_name: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={header_name: api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0, read=60.0),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.is_success:
            return response
        try:
            body = response.json()
        except ValueError:
            body = response.text[:4000]
        trace_id = body.get("traceId") if isinstance(body, dict) else None
        detail = body.get("detail") if isinstance(body, dict) else None
        raise GovernmentApiError(
            detail or f"Državni servis je vratio HTTP {response.status_code}",
            status_code=response.status_code,
            body=body,
            trace_id=trace_id,
        )


def json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text

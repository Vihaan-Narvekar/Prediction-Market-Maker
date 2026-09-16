from __future__ import annotations

from typing import Any

import httpx
import structlog
from eventmm.kalshi.http_budget import request_with_budget
from eventmm.kalshi.rate_limiter import TokenBucket

logger = structlog.get_logger()


class ExternalAPIClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 20.0,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.rate_limiter = TokenBucket(1, 1)
        self.response_hook = None
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.info("external_request_started", url=url, params=params)
        response = await request_with_budget(
            self.client,
            "GET",
            url,
            limiter=self.rate_limiter,
            response_hook=self.response_hook,
            params=params,
        )
        return response.json()

    async def close(self) -> None:
        await self.client.aclose()

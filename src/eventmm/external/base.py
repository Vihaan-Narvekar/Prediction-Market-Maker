from __future__ import annotations

from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


class ExternalAPIClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 20.0,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8)
    )
    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.info("external_request_started", url=url, params=params)
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        logger.info(
            "external_request_completed",
            url=url,
            status_code=response.status_code,
        )
        return response.json()

    async def close(self) -> None:
        await self.client.aclose()

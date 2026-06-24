from typing import Any

import httpx

from eventmm.external.base import ExternalAPIClient


class FREDClient(ExternalAPIClient):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.stlouisfed.org/fred",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        super().__init__(base_url, transport=transport)

    async def get_observations(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"series_id": series_id, "file_type": "json"}
        if self.api_key:
            params["api_key"] = self.api_key
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end
        return await self.get("/series/observations", params=params)

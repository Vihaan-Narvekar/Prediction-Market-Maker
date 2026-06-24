from typing import Any

import httpx
import structlog

from eventmm.external.base import ExternalAPIClient

logger = structlog.get_logger()


class BLSClient(ExternalAPIClient):
    def __init__(
        self,
        base_url: str = "https://api.bls.gov/publicAPI/v2/timeseries/data",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(base_url, transport=transport)

    async def get_timeseries(
        self,
        series_id: str,
        start_year: int,
        end_year: int,
    ) -> dict[str, Any]:
        logger.info(
            "external_request_started",
            url=self.base_url,
            series_id=series_id,
            start_year=start_year,
            end_year=end_year,
        )
        response = await self.client.post(
            self.base_url,
            json={
                "seriesid": [series_id],
                "startyear": str(start_year),
                "endyear": str(end_year),
            },
        )
        response.raise_for_status()
        logger.info(
            "external_request_completed",
            url=self.base_url,
            status_code=response.status_code,
        )
        return response.json()

from typing import Any

import httpx

from eventmm.external.base import ExternalAPIClient


class MissingNOAATokenError(ValueError):
    pass


class NOAAClient(ExternalAPIClient):
    def __init__(
        self,
        token: str | None,
        base_url: str = "https://www.ncei.noaa.gov/cdo-web/api/v2",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not token:
            raise MissingNOAATokenError("NOAA CDO token is required.")
        self.token = token
        super().__init__(base_url, headers={"token": token}, transport=transport)

    async def get_datasets(self) -> dict[str, Any]:
        return await self.get("/datasets")

    async def get_stations(self, location_id: str | None = None) -> dict[str, Any]:
        params = {"locationid": location_id} if location_id else None
        return await self.get("/stations", params=params)

    async def get_daily_data(
        self,
        dataset_id: str,
        station_id: str,
        start_date: str,
        end_date: str,
        datatype_ids: list[str],
    ) -> dict[str, Any]:
        rows = []
        offset = 1
        for _ in range(10000):
            page = await self.get(
                "/data",
                params={
                    "datasetid": dataset_id,
                    "stationid": station_id,
                    "startdate": start_date,
                    "enddate": end_date,
                    "datatypeid": ",".join(datatype_ids),
                    "limit": 1000,
                    "offset": offset,
                    "units": "standard",
                },
            )
            items = page.get("results", [])
            rows.extend(items)
            count = (
                page.get("metadata", {}).get("resultset", {}).get("count", len(rows))
            )
            if len(rows) >= count:
                return {**page, "results": rows}
            if not items:
                raise RuntimeError("NOAA pagination stopped before reported count")
            offset += len(items)
        raise RuntimeError("NOAA page budget exhausted")

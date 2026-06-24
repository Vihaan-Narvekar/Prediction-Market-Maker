import httpx

from eventmm.external.base import ExternalAPIClient


class NWSClient(ExternalAPIClient):
    def __init__(
        self,
        base_url: str = "https://api.weather.gov",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(
            base_url,
            headers={
                "Accept": "application/geo+json",
                "User-Agent": "eventmm-kalshi research client",
            },
            transport=transport,
        )

    async def get_point_metadata(self, lat: float, lon: float) -> dict:
        return await self.get(f"/points/{lat},{lon}")

    async def get_hourly_forecast(self, grid_id: str, grid_x: int, grid_y: int) -> dict:
        return await self.get(
            f"/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast/hourly"
        )

    async def get_gridpoint_forecast(
        self, grid_id: str, grid_x: int, grid_y: int
    ) -> dict:
        return await self.get(f"/gridpoints/{grid_id}/{grid_x},{grid_y}")

    async def get_observation_stations(
        self,
        grid_id: str,
        grid_x: int,
        grid_y: int,
    ) -> dict:
        return await self.get(f"/gridpoints/{grid_id}/{grid_x},{grid_y}/stations")

    async def get_station_observations(
        self,
        station_id: str,
        start: str,
        end: str,
    ) -> dict:
        return await self.get(
            f"/stations/{station_id}/observations",
            params={"start": start, "end": end},
        )

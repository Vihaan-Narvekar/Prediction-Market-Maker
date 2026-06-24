import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable


AsyncNoArg = Callable[[], Awaitable[None]]


@dataclass
class WeatherCollectorPipeline:
    locations: list[str]
    series: str
    interval_minutes: float
    collect_markets: AsyncNoArg
    collect_book_features: AsyncNoArg
    collect_forecasts: Callable[[str], Awaitable[None]]
    collect_noaa_observations: Callable[[str, str, str], Awaitable[None]]
    collect_labels: AsyncNoArg

    async def run_once(self) -> None:
        await self.collect_markets()
        await self.collect_book_features()
        for location in self.locations:
            await self.collect_forecasts(location)
        end = date.today()
        start = end - timedelta(days=7)
        for location in self.locations:
            await self.collect_noaa_observations(
                location, start.isoformat(), end.isoformat()
            )
        await self.collect_labels()

    async def run(self, iterations: int = 1) -> None:
        for iteration in range(iterations):
            await self.run_once()
            if iteration < iterations - 1:
                await asyncio.sleep(self.interval_minutes * 60)

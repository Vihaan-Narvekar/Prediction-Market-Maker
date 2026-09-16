import asyncio
import time
from datetime import datetime, timedelta, timezone

from eventmm.collector.archive import Archive
from eventmm.collector.weather_sources import _collect_noaa_daily, _collect_nws_forecast
from eventmm.kalshi.rate_limiter import TokenBucket


async def run_weather(
    source: str, locations: list[str], archive: Archive, interval: float
):
    if source not in {"nws", "noaa"} or interval <= 0 or not locations:
        raise ValueError("Valid source, locations and positive interval required")
    limiter = TokenBucket(1, 1)

    async def response_hook(response):
        archive.append(
            "weather_rest",
            {
                "url": str(response.request.url),
                "status": response.status_code,
                "body": response.text,
            },
        )

    def configure(client):
        client.rate_limiter = limiter
        client.response_hook = response_hook

    while True:
        for location in locations:
            if source == "nws":
                await _collect_nws_forecast(location, configure_client=configure)
            else:
                today = datetime.now(timezone.utc).date()
                await _collect_noaa_daily(
                    location,
                    str(today - timedelta(days=7)),
                    str(today),
                    configure_client=configure,
                )
        archive.checkpoint(
            "health",
            {"heartbeat": time.time(), "source": source, "locations": locations},
        )
        await asyncio.sleep(interval)

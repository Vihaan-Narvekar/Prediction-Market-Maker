"""Weather acquisition shared with the legacy one-shot CLI."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
import os

import orjson
import polars as pl
from rich.console import Console

from eventmm.config.settings import settings
from eventmm.external.forecast_versions import (
    append_forecast_version,
    build_nws_forecast_version_row,
)
from eventmm.external.noaa_client import NOAAClient
from eventmm.external.nws_client import NWSClient

console = Console()


def _now_slug():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(orjson.dumps(payload, default=str))
        output.flush()
        os.fsync(output.fileno())
    return path


WEATHER_LOCATIONS: dict[str, dict[str, Any]] = {
    "NYC": {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "stations": ["USW00094728", "USW00014732", "USW00094789"],
    },
    "CHICAGO": {
        "latitude": 41.8781,
        "longitude": -87.6298,
        "stations": ["KMDW", "KORD"],
    },
    "MIAMI": {"latitude": 25.7617, "longitude": -80.1918, "stations": ["KMIA"]},
    "AUSTIN": {"latitude": 30.2672, "longitude": -97.7431, "stations": ["KAUS"]},
    "BOSTON": {"latitude": 42.3601, "longitude": -71.0589, "stations": ["KBOS"]},
}


async def _collect_nws_forecast(location: str, *, configure_client=None) -> None:
    collection_ts = datetime.now(timezone.utc)
    loc = WEATHER_LOCATIONS[location.upper()]
    client = NWSClient()
    if configure_client:
        configure_client(client)
    try:
        point = await client.get_point_metadata(loc["latitude"], loc["longitude"])
        props = point["properties"]
        grid_id = props["gridId"]
        grid_x = props["gridX"]
        grid_y = props["gridY"]
        forecast = await client.get_hourly_forecast(grid_id, grid_x, grid_y)
    finally:
        await client.close()

    collection_ts = datetime.now(timezone.utc)
    raw_path = _write_json(
        settings.data_dir
        / "raw"
        / "external"
        / "nws"
        / f"location={location.upper()}"
        / f"{_now_slug()}.json",
        {"point": point, "forecast": forecast},
    )
    version_path = append_forecast_version(
        settings.data_dir,
        build_nws_forecast_version_row(
            location=location,
            collection_ts=collection_ts,
            raw_response_path=raw_path,
            forecast_payload=forecast,
        ),
    )

    rows = []
    for period in forecast.get("properties", {}).get("periods", []):
        rows.append(
            {
                "location": location.upper(),
                "collection_ts": collection_ts,
                "forecast_issue_ts": collection_ts,
                "source_issue_ts": forecast.get("properties", {}).get("updateTime")
                or forecast.get("properties", {}).get("generatedAt"),
                "forecast_start_ts": period.get("startTime"),
                "forecast_end_ts": period.get("endTime"),
                "forecast_valid_ts": period.get("startTime"),
                "forecast_date": str(period.get("startTime", ""))[:10],
                "forecast_temperature": period.get("temperature"),
                "temperature_unit": period.get("temperatureUnit"),
                "short_forecast": period.get("shortForecast"),
                "source": "nws_api",
                "raw_path": str(raw_path),
                "forecast_version_path": str(version_path),
            }
        )

    out_dir = settings.data_dir / "processed" / "external" / "nws_hourly_forecasts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"location={location.upper()}-{_now_slug()}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    console.print(f"Wrote {len(rows)} NWS forecast rows to {out_path}")
    console.print(f"Wrote forecast version row to {version_path}")


async def _collect_noaa_daily(
    location: str, start: str, end: str, *, configure_client=None
) -> None:
    loc = WEATHER_LOCATIONS[location.upper()]
    if any(not station.startswith("US") for station in loc["stations"]):
        raise ValueError("Configure verified GHCND station IDs for this location")
    client = NOAAClient(settings.noaa_cdo_token)
    if configure_client:
        configure_client(client)
    rows = []
    try:
        for station in loc["stations"]:
            payload = await client.get_daily_data(
                dataset_id="GHCND",
                station_id=f"GHCND:{station}",
                start_date=start,
                end_date=end,
                datatype_ids=["TMAX"],
            )
            _write_json(
                settings.data_dir
                / "raw"
                / "external"
                / "noaa"
                / f"location={location.upper()}"
                / f"station={station}-{_now_slug()}.json",
                payload,
            )
            for item in payload.get("results", []):
                rows.append(
                    {
                        "location": location.upper(),
                        "station_id": station,
                        "date": item.get("date", "")[:10],
                        "datatype": item.get("datatype"),
                        "value": item.get("value"),
                        "unit": "F",
                        "source": "noaa_cdo",
                        "received_ts": datetime.now(timezone.utc),
                    }
                )
    finally:
        await client.close()

    out_dir = settings.data_dir / "processed" / "external" / "noaa_daily_observations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir / f"location={location.upper()}-{start}-{end}-{_now_slug()}.parquet"
    )
    pl.DataFrame(rows).write_parquet(out_path)
    console.print(f"Wrote {len(rows)} NOAA observation rows to {out_path}")

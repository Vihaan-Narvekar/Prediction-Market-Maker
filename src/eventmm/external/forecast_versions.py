from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from eventmm.utils.files import file_sha256


def build_nws_forecast_version_row(
    *,
    location: str,
    collection_ts: datetime,
    raw_response_path: Path,
    forecast_payload: dict[str, Any],
) -> dict[str, Any]:
    periods = forecast_payload.get("properties", {}).get("periods", [])
    valid_starts = [
        period.get("startTime") for period in periods if period.get("startTime")
    ]
    valid_ends = [period.get("endTime") for period in periods if period.get("endTime")]
    generated_at = forecast_payload.get("properties", {}).get("generatedAt")
    updated_at = (
        forecast_payload.get("properties", {}).get("updateTime") or generated_at
    )

    return {
        "source": "nws_api",
        "location": location.upper(),
        "collection_ts": collection_ts,
        "forecast_generated_at": generated_at,
        "forecast_updated_at": updated_at,
        "forecast_valid_start": min(valid_starts) if valid_starts else None,
        "forecast_valid_end": max(valid_ends) if valid_ends else None,
        "raw_response_path": str(raw_response_path),
        "hash": file_sha256(raw_response_path),
    }


def append_forecast_version(base_dir: Path, row: dict[str, Any]) -> Path:
    out_dir = base_dir / "processed" / "external" / "forecast_versions"
    out_dir.mkdir(parents=True, exist_ok=True)
    collection_ts = row.get("collection_ts") or datetime.now(timezone.utc)
    if isinstance(collection_ts, datetime):
        slug = collection_ts.strftime("%Y%m%dT%H%M%SZ")
    else:
        slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = (
        out_dir / f"source={row['source']}-location={row['location']}-{slug}.parquet"
    )
    pl.DataFrame([row]).write_parquet(out_path)
    return out_path

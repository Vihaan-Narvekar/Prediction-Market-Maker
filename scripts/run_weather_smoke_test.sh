#!/usr/bin/env bash
set -euo pipefail

LOCATION="${LOCATION:-NYC}"
SERIES="${SERIES:-KXHIGHNY}"
DATASET="${DATASET:-weather_nyc_smoke_v1}"
START="${START:-2026-06-01}"
END="${END:-2026-06-23}"

uv run eventmm collect-nws-forecast --location "$LOCATION"
uv run eventmm collect-noaa-daily --location "$LOCATION" --start "$START" --end "$END"
uv run eventmm markets --series "$SERIES" --status open --limit 50
uv run eventmm markets --series "$SERIES" --status closed --limit 50
uv run eventmm parse-contracts --series "$SERIES"
uv run eventmm build-labels --series "$SERIES"
uv run eventmm build-dataset --name "$DATASET" --start "$START" --end "$END"
uv run eventmm validate-dataset --name "$DATASET"
uv run eventmm add-baseline-features --dataset "$DATASET"
uv run eventmm datasets describe "$DATASET"

#!/usr/bin/env bash
set -euo pipefail

LOCATIONS="${LOCATIONS:-NYC}"
SERIES="${SERIES:-KXHIGHNY}"
SLEEP_SECONDS="${SLEEP_SECONDS:-300}"
MAX_AGE_MINUTES="${MAX_AGE_MINUTES:-30}"
LOG_DIR="${LOG_DIR:-logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/weather_collector.log}"

mkdir -p "${LOG_DIR}"

while true; do
  {
    echo "collector run: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    uv run eventmm run-weather-collector \
      --locations "${LOCATIONS}" \
      --series "${SERIES}" \
      --iterations 1
    uv run eventmm collector health \
      --series "${SERIES}" \
      --since 24h
    uv run eventmm collector freshness \
      --series "${SERIES}" \
      --max-age-minutes "${MAX_AGE_MINUTES}"
  } >> "${LOG_FILE}" 2>&1

  sleep "${SLEEP_SECONDS}"
done

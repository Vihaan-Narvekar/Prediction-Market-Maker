#!/usr/bin/env bash
set -euo pipefail
# Pass repeated --series / --location flags explicitly to override these defaults.
if [ "$#" -eq 0 ]; then
  set -- --series KXHIGHNY --location NYC
fi
exec uv run python -m eventmm.collector_cli supervise "$@"

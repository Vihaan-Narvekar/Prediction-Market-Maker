import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ModelRegistry:
    def __init__(self, registry_dir: Path = Path("artifacts/metrics")):
        self.registry_dir = registry_dir
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def write_run(self, run_name: str, metadata: dict[str, Any]) -> Path:
        payload = {
            "run_name": run_name,
            "created_ts": datetime.now(timezone.utc).isoformat(),
            **metadata,
        }
        path = self.registry_dir / f"{run_name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return path

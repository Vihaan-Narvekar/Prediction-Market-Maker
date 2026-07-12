import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from eventmm.utils.files import file_sha256


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_dataset_manifest(
    dataset_dir: Path,
    *,
    dataset_name: str,
    source_paths: dict[str, list[Path]],
    build_config: dict[str, Any],
) -> Path:
    outputs = sorted(dataset_dir.glob("*.parquet"))
    if not outputs:
        raise ValueError(f"No parquet outputs found in {dataset_dir}.")
    dataset = pl.concat(
        [pl.read_parquet(path) for path in outputs], how="diagonal_relaxed"
    )
    payload = {
        "manifest_version": 1,
        "dataset_name": dataset_name,
        "created_ts": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(),
        "build_config": build_config,
        "row_count": len(dataset),
        "columns": [
            {"name": name, "dtype": str(dtype)}
            for name, dtype in dataset.schema.items()
        ],
        "outputs": [
            {
                "path": str(path),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in outputs
        ],
        "sources": {
            name: [
                {
                    "path": str(path),
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(paths)
            ]
            for name, paths in sorted(source_paths.items())
        },
    }
    manifest_path = dataset_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return manifest_path


def verify_dataset_manifest(path: Path) -> list[str]:
    payload = json.loads(path.read_text())
    errors: list[str] = []
    for group in [payload.get("outputs", [])] + list(
        payload.get("sources", {}).values()
    ):
        for item in group:
            file_path = Path(item["path"])
            if not file_path.exists():
                errors.append(f"missing: {file_path}")
            elif file_sha256(file_path) != item["sha256"]:
                errors.append(f"hash mismatch: {file_path}")
    return errors

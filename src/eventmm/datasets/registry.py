import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from eventmm.utils.files import hash_paths


class DatasetRegistry:
    def __init__(self, registry_dir: Path):
        self.registry_dir = registry_dir
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.registry_dir / f"{name}.json"

    def write_metadata(
        self,
        name: str,
        *,
        start: str,
        end: str,
        market_universe: str,
        sources: dict[str, str],
        feature_tables: list[str],
        label_table: str,
        row_counts: dict[str, int] | None = None,
        missingness: dict[str, float] | None = None,
        config_snapshot: dict[str, Any] | None = None,
        dataset_hash: str | None = None,
        feature_columns: list[str] | None = None,
        label_column: str = "label",
        validation_status: str | None = None,
        source_tables: list[str] | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "dataset_name": name,
            "created_ts": datetime.now(timezone.utc).isoformat(),
            "start": start,
            "end": end,
            "market_universe": market_universe,
            "sources": sources,
            "feature_tables": feature_tables,
            "label_table": label_table,
            "row_counts": row_counts or {},
            "missingness": missingness or {},
            "config_snapshot": config_snapshot or {},
            "dataset_hash": dataset_hash,
            "feature_columns": feature_columns or [],
            "label_column": label_column,
            "validation_status": validation_status,
            "source_tables": source_tables or feature_tables + [label_table],
        }
        self._path(name).write_text(json.dumps(metadata, indent=2, sort_keys=True))
        return metadata

    def list_datasets(self) -> list[str]:
        return sorted(path.stem for path in self.registry_dir.glob("*.json"))

    def describe(self, name: str) -> dict[str, Any]:
        return json.loads(self._path(name).read_text())

    def update_metadata(self, name: str, updates: dict[str, Any]) -> dict[str, Any]:
        metadata = self.describe(name)
        metadata.update(updates)
        self._path(name).write_text(json.dumps(metadata, indent=2, sort_keys=True))
        return metadata


def dataset_metadata_from_parquet(
    dataset_dir: Path,
    *,
    feature_columns: list[str] | None = None,
    label_column: str = "label",
) -> dict[str, Any]:
    paths = list(dataset_dir.glob("*.parquet"))
    if not paths:
        return {
            "dataset_hash": None,
            "row_count": 0,
            "market_count": 0,
            "label_count": 0,
            "feature_columns": feature_columns or [],
            "label_column": label_column,
        }

    df = pl.concat([pl.read_parquet(path) for path in paths], how="diagonal_relaxed")
    inferred_features = feature_columns or [
        col
        for col in df.columns
        if col
        not in {
            label_column,
            "market_ticker",
            "as_of_ts",
            "result",
            "label_source",
            "label_quality",
        }
    ]
    return {
        "dataset_hash": hash_paths(paths),
        "row_count": len(df),
        "market_count": df.select("market_ticker").n_unique()
        if "market_ticker" in df.columns
        else 0,
        "label_count": df.filter(pl.col(label_column).is_not_null()).height
        if label_column in df.columns
        else 0,
        "feature_columns": inferred_features,
        "label_column": label_column,
    }

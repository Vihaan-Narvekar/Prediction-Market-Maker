from pathlib import Path
import time
from typing import Any

import polars as pl


class BufferedParquetWriter:
    def __init__(self, base_dir: Path, dataset_name: str, flush_size: int = 1000):
        self.base_dir = base_dir
        self.dataset_name = dataset_name
        self.flush_size = flush_size
        self.buffer: list[dict[str, Any]] = []

    def append(self, row: dict[str, Any]) -> None:
        self.buffer.append(row)
        if len(self.buffer) >= self.flush_size:
            self.flush()

    def flush(self) -> Path | None:
        if not self.buffer:
            return None

        out_dir = self.base_dir / self.dataset_name
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"part-{time.time_ns()}.parquet"
        pl.DataFrame(self.buffer).write_parquet(out_path)
        self.buffer.clear()
        return out_path

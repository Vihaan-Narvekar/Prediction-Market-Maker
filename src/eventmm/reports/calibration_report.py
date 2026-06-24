from pathlib import Path

import polars as pl


def write_calibration_report(path: Path, table: pl.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Calibration Report\n\n" + table.write_csv())
    return path

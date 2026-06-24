from dataclasses import dataclass
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class ModelingDataset:
    X: pl.DataFrame
    y: pl.Series
    metadata: pl.DataFrame
    feature_names: list[str]
    label_col: str


def load_modeling_dataset(
    dataset_name: str,
    feature_cols: list[str],
    label_col: str = "label",
    data_dir: Path = Path("data/processed/datasets"),
) -> ModelingDataset:
    dataset_dir = data_dir / dataset_name
    paths = list(dataset_dir.glob("*.parquet"))
    if not paths:
        raise ValueError(f"No parquet files found for dataset {dataset_name}.")

    df = pl.concat([pl.read_parquet(path) for path in paths], how="diagonal_relaxed")
    required = feature_cols + [label_col, "market_ticker", "as_of_ts"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.drop_nulls(feature_cols + [label_col])
    metadata_cols = [
        column
        for column in (
            "market_ticker",
            "as_of_ts",
            "market_mid",
            "market_microprice",
            "market_spread",
            "contract_date",
            "threshold_value",
        )
        if column in df.columns
    ]

    return ModelingDataset(
        X=df.select(feature_cols),
        y=df[label_col],
        metadata=df.select(metadata_cols),
        feature_names=feature_cols,
        label_col=label_col,
    )

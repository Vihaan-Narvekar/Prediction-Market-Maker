from pathlib import Path

import polars as pl

from eventmm.datasets.joins import asof_join_market_weather
from eventmm.datasets.registry import DatasetRegistry, dataset_metadata_from_parquet


def build_weather_dataset(
    *,
    name: str,
    start: str,
    end: str,
    data_dir: Path,
    market_features: pl.DataFrame,
    weather_forecasts: pl.DataFrame,
    contract_specs: pl.DataFrame,
    labels: pl.DataFrame | None = None,
    observations: pl.DataFrame | None = None,
) -> Path:
    dataset = asof_join_market_weather(
        market_features=market_features,
        weather_forecasts=weather_forecasts,
        contract_specs=contract_specs,
        labels=labels,
        observations=observations,
    )
    out_dir = data_dir / "processed" / "datasets" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.parquet"
    dataset.write_parquet(out_path)
    dataset_meta = dataset_metadata_from_parquet(out_dir)

    DatasetRegistry(data_dir / "registry").write_metadata(
        name,
        start=start,
        end=end,
        market_universe="weather",
        sources={
            "kalshi": "book_features",
            "nws": "forecast/hourly",
            "noaa": "daily observations",
        },
        feature_tables=[
            "book_features",
            "nws_hourly_forecasts",
            "weather_contract_specs",
        ],
        label_table="market_outcomes",
        row_counts={
            "dataset": dataset_meta["row_count"],
            "markets": dataset_meta["market_count"],
            "labels": dataset_meta["label_count"],
        },
        missingness={
            column: float(
                dataset.filter(pl.col(column).is_null()).height / len(dataset)
            )
            for column in ("forecast_temperature", "observed_temperature", "label")
            if column in dataset.columns and len(dataset) > 0
        },
        dataset_hash=dataset_meta["dataset_hash"],
        feature_columns=dataset_meta["feature_columns"],
        label_column=dataset_meta["label_column"],
        validation_status="not_validated",
        source_tables=[
            "book_features",
            "nws_hourly_forecasts",
            "noaa_daily_observations",
            "weather_contract_specs",
            "market_outcomes",
        ],
    )
    return out_path

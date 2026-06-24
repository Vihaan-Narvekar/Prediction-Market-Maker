from pathlib import Path

import polars as pl


class BacktestDataError(ValueError):
    pass


def load_backtest_dataset(
    dataset: str, data_dir: Path = Path("data/processed/datasets")
) -> pl.DataFrame:
    paths = list((data_dir / dataset).glob("*.parquet"))
    if not paths:
        raise BacktestDataError(f"No parquet files found for dataset {dataset}.")
    df = pl.concat([pl.read_parquet(path) for path in paths], how="diagonal_relaxed")
    required = ["market_ticker", "as_of_ts", "label"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise BacktestDataError(f"Missing required backtest columns: {missing}")
    if "forecast_issue_ts" in df.columns:
        leakage = df.filter(
            pl.col("forecast_issue_ts").is_not_null()
            & (pl.col("forecast_issue_ts") > pl.col("as_of_ts"))
        )
        if len(leakage) > 0:
            raise BacktestDataError("Future forecast leakage detected.")
    return df


def summarize_backtest_data(df: pl.DataFrame) -> dict[str, int | str]:
    return {
        "rows": len(df),
        "markets": df.select("market_ticker").n_unique()
        if "market_ticker" in df.columns
        else 0,
        "resolved_markets": df.drop_nulls(["label"]).select("market_ticker").n_unique()
        if "label" in df.columns
        else 0,
        "timestamp_start": str(df.select(pl.col("as_of_ts").min()).item())
        if "as_of_ts" in df.columns and len(df)
        else "",
        "timestamp_end": str(df.select(pl.col("as_of_ts").max()).item())
        if "as_of_ts" in df.columns and len(df)
        else "",
        "book_rows": df.drop_nulls(["market_mid"]).height
        if "market_mid" in df.columns
        else 0,
        "forecast_rows": df.drop_nulls(["forecast_temperature"]).height
        if "forecast_temperature" in df.columns
        else 0,
        "label_rows": df.drop_nulls(["label"]).height if "label" in df.columns else 0,
    }

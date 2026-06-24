import polars as pl


class DatasetValidationError(Exception):
    pass


def weather_validation_summary(df: pl.DataFrame) -> dict[str, int]:
    rows = len(df)
    markets = (
        df.select("market_ticker").n_unique() if "market_ticker" in df.columns else 0
    )

    duplicate_rows = 0
    if {"market_ticker", "as_of_ts"}.issubset(df.columns):
        duplicate_rows = (
            df.group_by(["market_ticker", "as_of_ts"])
            .len()
            .filter(pl.col("len") > 1)
            .height
        )

    future_leakage_rows = 0
    if {"forecast_issue_ts", "as_of_ts"}.issubset(df.columns):
        future_leakage_rows = df.filter(
            pl.col("forecast_issue_ts").is_not_null()
            & (pl.col("forecast_issue_ts") > pl.col("as_of_ts"))
        ).height

    impossible_temperatures = 0
    if "forecast_temperature" in df.columns:
        impossible_temperatures = df.filter(
            pl.col("forecast_temperature").is_not_null()
            & (
                (pl.col("forecast_temperature") < -100)
                | (pl.col("forecast_temperature") > 150)
            )
        ).height

    return {
        "rows": rows,
        "markets": markets,
        "duplicate_market_timestamp_rows": duplicate_rows,
        "future_forecast_leakage_rows": future_leakage_rows,
        "missing_labels": df.filter(pl.col("label").is_null()).height
        if "label" in df.columns
        else rows,
        "missing_forecast_rows": df.filter(
            pl.col("forecast_temperature").is_null()
        ).height
        if "forecast_temperature" in df.columns
        else rows,
        "missing_thresholds": df.filter(pl.col("threshold_value").is_null()).height
        if "threshold_value" in df.columns
        else rows,
        "impossible_temperatures": impossible_temperatures,
        "unresolved_markets": df.filter(pl.col("label").is_null()).height
        if "label" in df.columns
        else rows,
    }


def validate_no_future_leakage(df: pl.DataFrame) -> None:
    if {"forecast_issue_ts", "as_of_ts"}.issubset(df.columns):
        bad = df.filter(
            pl.col("forecast_issue_ts").is_not_null()
            & (pl.col("forecast_issue_ts") > pl.col("as_of_ts"))
        )
        if len(bad) > 0:
            raise DatasetValidationError("Future weather forecast leakage detected.")


def validate_no_missing_market_ticker(df: pl.DataFrame) -> None:
    if (
        "market_ticker" not in df.columns
        or df.filter(pl.col("market_ticker").is_null()).height > 0
    ):
        raise DatasetValidationError("Missing market_ticker values detected.")


def validate_no_duplicate_market_timestamps(df: pl.DataFrame) -> None:
    if {"market_ticker", "as_of_ts"}.issubset(df.columns):
        duplicates = (
            df.group_by(["market_ticker", "as_of_ts"]).len().filter(pl.col("len") > 1)
        )
        if len(duplicates) > 0:
            raise DatasetValidationError(
                "Duplicate market_ticker/as_of_ts rows detected."
            )


def validate_labels(df: pl.DataFrame, require_resolved: bool = True) -> None:
    if "label" not in df.columns:
        if require_resolved:
            raise DatasetValidationError("Missing label column.")
        return
    invalid = df.filter(pl.col("label").is_not_null() & ~pl.col("label").is_in([0, 1]))
    if len(invalid) > 0:
        raise DatasetValidationError("Invalid labels detected.")
    if require_resolved and df.filter(pl.col("label").is_null()).height > 0:
        raise DatasetValidationError("Unresolved labels detected.")


def validate_weather_dataset(
    df: pl.DataFrame, require_resolved: bool = True
) -> dict[str, int]:
    summary = weather_validation_summary(df)
    validate_no_missing_market_ticker(df)
    validate_no_duplicate_market_timestamps(df)
    validate_no_future_leakage(df)
    validate_labels(df, require_resolved=require_resolved)

    if "threshold_value" in df.columns:
        missing_thresholds = df.filter(pl.col("threshold_value").is_null()).height
        if missing_thresholds > 0:
            raise DatasetValidationError("Missing threshold values detected.")
    else:
        missing_thresholds = len(df)

    if "forecast_temperature" in df.columns:
        impossible = df.filter(
            pl.col("forecast_temperature").is_not_null()
            & (
                (pl.col("forecast_temperature") < -100)
                | (pl.col("forecast_temperature") > 150)
            )
        ).height
        if impossible > 0:
            raise DatasetValidationError("Impossible forecast temperatures detected.")

    summary["missing_thresholds"] = missing_thresholds
    return summary

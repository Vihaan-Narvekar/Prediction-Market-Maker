import polars as pl


def add_weather_baseline_features(df: pl.DataFrame) -> pl.DataFrame:
    expressions = []
    if {"forecast_temperature", "threshold_value"}.issubset(df.columns):
        expressions.extend(
            [
                (pl.col("forecast_temperature") - pl.col("threshold_value")).alias(
                    "forecast_minus_threshold"
                ),
                (pl.col("forecast_temperature") - pl.col("threshold_value"))
                .abs()
                .alias("abs_forecast_distance_to_threshold"),
                (pl.col("forecast_temperature") > pl.col("threshold_value"))
                .cast(pl.Int8)
                .alias("forecast_above_threshold"),
            ]
        )
    if {"expiration_time", "as_of_ts"}.issubset(df.columns):
        expressions.append(
            (
                (
                    pl.col("expiration_time").cast(pl.Datetime)
                    - pl.col("as_of_ts").cast(pl.Datetime)
                ).dt.total_seconds()
                / 3600
            ).alias("time_to_expiry_hours")
        )
    if {"market_microprice", "market_mid"}.issubset(df.columns):
        expressions.append(
            (pl.col("market_microprice") - pl.col("market_mid")).alias(
                "microprice_minus_mid"
            )
        )
    if not expressions:
        return df
    return df.with_columns(expressions)

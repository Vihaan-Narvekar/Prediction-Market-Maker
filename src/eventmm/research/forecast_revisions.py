import polars as pl


def add_forecast_revision_features(df: pl.DataFrame) -> pl.DataFrame:
    required = {
        "location",
        "forecast_date",
        "forecast_issue_ts",
        "forecast_temperature",
    }
    if not required.issubset(df.columns):
        missing = sorted(required - set(df.columns))
        raise ValueError(f"Missing forecast revision columns: {missing}")
    daily = (
        df.group_by(["location", "forecast_date", "forecast_issue_ts"])
        .agg(pl.col("forecast_temperature").max().alias("forecast_temperature"))
        .sort(["location", "forecast_date", "forecast_issue_ts"])
    )
    prior = pl.col("forecast_temperature").shift(1).over(["location", "forecast_date"])
    prior_issue = (
        pl.col("forecast_issue_ts").shift(1).over(["location", "forecast_date"])
    )
    return daily.with_columns(
        prior.alias("prior_forecast_temperature"),
        prior_issue.alias("prior_forecast_issue_ts"),
    ).with_columns(
        (pl.col("forecast_temperature") - pl.col("prior_forecast_temperature")).alias(
            "forecast_revision"
        ),
        pl.col("forecast_issue_ts")
        .diff()
        .over(["location", "forecast_date"])
        .dt.total_minutes()
        .alias("minutes_since_prior_forecast"),
        pl.col("forecast_temperature")
        .cum_max()
        .over(["location", "forecast_date"])
        .alias("forecast_high_so_far"),
        pl.col("forecast_temperature")
        .cum_min()
        .over(["location", "forecast_date"])
        .alias("forecast_low_so_far"),
    )

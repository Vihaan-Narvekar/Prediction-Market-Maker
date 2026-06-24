import polars as pl


def asof_join_market_weather(
    market_features: pl.DataFrame,
    weather_forecasts: pl.DataFrame,
    contract_specs: pl.DataFrame,
    labels: pl.DataFrame | None = None,
    observations: pl.DataFrame | None = None,
) -> pl.DataFrame:
    joined = market_features.join(contract_specs, on="market_ticker", how="left")

    joined = joined.with_columns(
        pl.col("as_of_ts").cast(pl.Datetime),
        pl.col("contract_date").cast(pl.Date),
    )
    forecasts = weather_forecasts.with_columns(
        pl.col("forecast_issue_ts").cast(pl.Datetime),
        pl.col("forecast_date").cast(pl.Date),
    )

    rows: list[dict] = []
    for row in joined.to_dicts():
        candidates = forecasts.filter(
            (pl.col("location") == row.get("location"))
            & (pl.col("forecast_date") == row.get("contract_date"))
            & (pl.col("forecast_issue_ts") <= row.get("as_of_ts"))
        ).sort("forecast_issue_ts")

        out = dict(row)
        if len(candidates) > 0:
            latest = candidates.tail(1).to_dicts()[0]
            out.update(
                {
                    "forecast_issue_ts": latest.get("forecast_issue_ts"),
                    "forecast_temperature": latest.get("forecast_temperature"),
                    "external_source": latest.get("source"),
                }
            )
        else:
            out.update(
                {
                    "forecast_issue_ts": None,
                    "forecast_temperature": None,
                    "external_source": None,
                }
            )
        out["observed_temperature"] = None
        out["observation_station_id"] = None
        rows.append(out)

    result = pl.DataFrame(rows) if rows else joined
    if observations is not None and len(observations) > 0:
        obs = observations.with_columns(
            pl.col("date").cast(pl.Date),
            pl.col("value").cast(pl.Float64).alias("observed_temperature"),
        )
        obs = (
            obs.sort(["location", "date", "station_id"])
            .group_by(["location", "date"])
            .first()
            .select(
                "location",
                pl.col("date").alias("contract_date"),
                "station_id",
                "observed_temperature",
            )
        )
        result = result.drop(
            [
                col
                for col in ("observed_temperature", "observation_station_id")
                if col in result.columns
            ]
        ).join(obs, on=["location", "contract_date"], how="left")
        if "station_id" in result.columns:
            result = result.rename({"station_id": "observation_station_id"})
    if labels is not None and len(labels) > 0:
        label_columns = [
            column
            for column in (
                "market_ticker",
                "result",
                "label",
                "label_source",
                "label_quality",
                "label_confidence",
                "settlement_rule_match",
                "observed_source",
                "observed_station",
                "observed_value",
                "kalshi_result",
                "observed_result",
                "label_disagreement_flag",
                "settlement_time",
            )
            if column in labels.columns
        ]
        result = result.join(
            labels.select(label_columns), on="market_ticker", how="left"
        )
    return result

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

import polars as pl

from eventmm.research.forecast_revisions import add_forecast_revision_features


def _date(value: Any) -> date:
    return (
        value
        if isinstance(value, date) and not isinstance(value, datetime)
        else date.fromisoformat(str(value)[:10])
    )


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def _lead_bucket(issue_ts: Any, forecast_date: Any) -> str:
    target = datetime.combine(_date(forecast_date), time(23, 59), tzinfo=timezone.utc)
    hours = (target - _utc(issue_ts)).total_seconds() / 3600
    if hours <= 12:
        return "0-12h"
    if hours <= 24:
        return "12-24h"
    if hours <= 48:
        return "24-48h"
    return "48h+"


def _revision_bucket(revision: float | None) -> str:
    if revision is None or revision == 0:
        return "unchanged"
    return "warming" if revision > 0 else "cooling"


def build_forecast_error_samples(
    forecasts: pl.DataFrame, observations: pl.DataFrame
) -> pl.DataFrame:
    revisions = add_forecast_revision_features(forecasts).select(
        "location",
        "forecast_date",
        "forecast_issue_ts",
        "forecast_temperature",
        "forecast_revision",
    )
    observed = (
        observations.with_columns(
            pl.col("date").cast(pl.Date).alias("forecast_date"),
            pl.col("value").cast(pl.Float64).alias("observed_temperature"),
        )
        .group_by(["location", "forecast_date"])
        .agg(pl.col("observed_temperature").max())
    )
    joined = revisions.with_columns(pl.col("forecast_date").cast(pl.Date)).join(
        observed, on=["location", "forecast_date"], how="inner"
    )
    if len(joined) == 0:
        return joined
    return joined.with_columns(
        (pl.col("observed_temperature") - pl.col("forecast_temperature")).alias(
            "forecast_error"
        ),
        pl.struct("forecast_issue_ts", "forecast_date")
        .map_elements(
            lambda row: _lead_bucket(row["forecast_issue_ts"], row["forecast_date"]),
            return_dtype=pl.String,
        )
        .alias("lead_time_bucket"),
        pl.col("forecast_revision")
        .map_elements(_revision_bucket, return_dtype=pl.String)
        .alias("revision_bucket"),
    )


@dataclass(frozen=True)
class ProbabilityEstimate:
    probability: float | None
    sample_size: int
    source: str


class EmpiricalForecastErrorModel:
    def __init__(self, samples: pl.DataFrame, min_samples: int = 10):
        self.samples = samples
        self.min_samples = min_samples

    def estimate(
        self,
        contract: dict[str, Any],
        *,
        forecast_temperature: float,
        forecast_issue_ts: Any,
        forecast_date: Any,
        forecast_revision: float | None = None,
    ) -> ProbabilityEstimate:
        target_date = _date(forecast_date)
        prior = self.samples.filter(
            (pl.col("location") == contract.get("location"))
            & (pl.col("forecast_date") < target_date)
        )
        bucket = _lead_bucket(forecast_issue_ts, target_date)
        bucketed = prior.filter(pl.col("lead_time_bucket") == bucket)
        revision_bucket = _revision_bucket(forecast_revision)
        conditioned = bucketed.filter(pl.col("revision_bucket") == revision_bucket)
        if len(conditioned) >= self.min_samples:
            selected = conditioned
            source = f"lead_and_revision:{bucket}:{revision_bucket}"
        elif len(bucketed) >= self.min_samples:
            selected = bucketed
            source = f"lead_bucket:{bucket}"
        else:
            selected = prior
            source = "pooled_prior_dates"
        if len(selected) < self.min_samples:
            return ProbabilityEstimate(None, len(selected), "insufficient_prior_errors")
        outcomes = [
            _contract_outcome(contract, forecast_temperature + float(error))
            for error in selected["forecast_error"].to_list()
        ]
        probability = (sum(outcomes) + 0.5) / (len(outcomes) + 1)
        return ProbabilityEstimate(float(probability), len(outcomes), source)


def _contract_outcome(contract: dict[str, Any], temperature: float) -> int:
    threshold = float(contract["threshold_value"])
    if contract.get("contract_type") == "range":
        upper = contract.get("threshold_upper_value")
        return int(upper is not None and threshold <= temperature <= float(upper))
    if contract.get("comparison_operator") == "<":
        return int(temperature < threshold)
    return int(temperature > threshold)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import copysign
from typing import Any

import polars as pl

from eventmm.backtest.fees import FeeModel
from eventmm.research.forecast_error_model import (
    EmpiricalForecastErrorModel,
    ProbabilityEstimate,
    build_forecast_error_samples,
)
from eventmm.research.forecast_revisions import add_forecast_revision_features


HORIZONS_MINUTES: dict[str, float] = {
    "first_post": 0.0,
    "1m": 1.0,
    "5m": 5.0,
    "15m": 15.0,
    "30m": 30.0,
}


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


def _indicator(row: dict[str, Any], temperature: float) -> int:
    threshold = float(row["threshold_value"])
    if row.get("contract_type") == "range":
        upper = row.get("threshold_upper_value")
        return int(upper is not None and threshold <= temperature <= float(upper))
    if row.get("comparison_operator") == "<":
        return int(temperature < threshold)
    return int(temperature > threshold)


def _expected_direction(row: dict[str, Any], prior: float, current: float) -> int:
    revision_sign = 0 if current == prior else int(copysign(1, current - prior))
    if row.get("contract_type") == "range":
        upper = row.get("threshold_upper_value")
        if upper is None:
            return 0
        center = (float(row["threshold_value"]) + float(upper)) / 2
        old_distance = abs(prior - center)
        new_distance = abs(current - center)
        return (
            0
            if new_distance == old_distance
            else (1 if new_distance < old_distance else -1)
        )
    return -revision_sign if row.get("comparison_operator") == "<" else revision_sign


def _quote_at_or_after(
    quotes: list[dict[str, Any]], target: datetime, max_lag: timedelta
) -> dict[str, Any] | None:
    return next(
        (row for row in quotes if target <= row["_ts"] <= target + max_lag), None
    )


def _fee_adjusted_edges(
    row: dict[str, Any], probability: float | None, fee_model: FeeModel
) -> tuple[float | None, float | None]:
    if probability is None:
        return None, None
    yes_ask = row.get("best_yes_ask")
    no_ask = row.get("best_no_ask")
    yes_edge = (
        None
        if yes_ask is None
        else probability * 100
        - float(yes_ask)
        - fee_model.estimate_fee_cents(float(yes_ask), 1, "taker")
    )
    no_edge = (
        None
        if no_ask is None
        else (1 - probability) * 100
        - float(no_ask)
        - fee_model.estimate_fee_cents(float(no_ask), 1, "taker")
    )
    return yes_edge, no_edge


def build_forecast_revision_event_study(
    quotes: pl.DataFrame,
    forecasts: pl.DataFrame,
    observations: pl.DataFrame | None = None,
    *,
    max_pre_age_minutes: float = 30,
    max_horizon_lag_minutes: float = 20,
    min_incorporation_move_cents: float = 1,
    fee_model: FeeModel | None = None,
) -> pl.DataFrame:
    fee_model = fee_model or FeeModel()
    probability_model = (
        EmpiricalForecastErrorModel(
            build_forecast_error_samples(forecasts, observations), min_samples=10
        )
        if observations is not None
        else None
    )
    revisions = add_forecast_revision_features(forecasts).filter(
        pl.col("forecast_revision").is_not_null() & (pl.col("forecast_revision") != 0)
    )
    quote_rows = quotes.filter(pl.col("market_mid").is_not_null()).to_dicts()
    for row in quote_rows:
        row["_ts"] = _utc(row["as_of_ts"])
    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in quote_rows:
        by_market.setdefault(str(row["market_ticker"]), []).append(row)
    for rows in by_market.values():
        rows.sort(key=lambda item: item["_ts"])

    contracts = (
        quotes.select(
            "market_ticker",
            "event_ticker",
            "location",
            "contract_date",
            "contract_type",
            "comparison_operator",
            "threshold_value",
            "threshold_upper_value",
        )
        .unique("market_ticker", keep="last")
        .to_dicts()
    )
    results: list[dict[str, Any]] = []
    max_pre_age = timedelta(minutes=max_pre_age_minutes)
    max_lag = timedelta(minutes=max_horizon_lag_minutes)
    for revision_id, revision in enumerate(revisions.to_dicts(), start=1):
        issue = _utc(revision["forecast_issue_ts"])
        prior_temp = float(revision["prior_forecast_temperature"])
        current_temp = float(revision["forecast_temperature"])
        matching = [
            contract
            for contract in contracts
            if str(contract.get("location")) == str(revision["location"])
            and str(contract.get("contract_date")) == str(revision["forecast_date"])
        ]
        for contract in matching:
            market_quotes = by_market.get(str(contract["market_ticker"]), [])
            pre = next(
                (
                    row
                    for row in reversed(market_quotes)
                    if issue - max_pre_age <= row["_ts"] <= issue
                ),
                None,
            )
            if pre is None:
                continue
            expected_direction = _expected_direction(contract, prior_temp, current_temp)
            pre_probability = _indicator(contract, prior_temp)
            prior_estimate = _probability_estimate(
                probability_model,
                contract,
                prior_temp,
                revision["prior_forecast_issue_ts"],
                revision["forecast_date"],
                float(revision["forecast_revision"]),
            )
            current_estimate = _probability_estimate(
                probability_model,
                contract,
                current_temp,
                revision["forecast_issue_ts"],
                revision["forecast_date"],
                float(revision["forecast_revision"]),
            )
            pre_yes_edge, pre_no_edge = _fee_adjusted_edges(
                pre, prior_estimate.probability, fee_model
            )
            aligned_quotes = [
                (
                    "pre",
                    issue,
                    pre,
                    pre_probability,
                    prior_estimate,
                    pre_yes_edge,
                    pre_no_edge,
                )
            ]
            for horizon, minutes in HORIZONS_MINUTES.items():
                target = issue + timedelta(minutes=minutes)
                post = _quote_at_or_after(market_quotes, target, max_lag)
                if post is not None:
                    probability = _indicator(contract, current_temp)
                    yes_edge, no_edge = _fee_adjusted_edges(
                        post, current_estimate.probability, fee_model
                    )
                    aligned_quotes.append(
                        (
                            horizon,
                            target,
                            post,
                            probability,
                            current_estimate,
                            yes_edge,
                            no_edge,
                        )
                    )
            for (
                horizon,
                target,
                quote,
                probability,
                estimate,
                yes_edge,
                no_edge,
            ) in aligned_quotes:
                midpoint_change = float(quote["market_mid"]) - float(pre["market_mid"])
                pre_depth = _top_depth(pre)
                quote_depth = _top_depth(quote)
                results.append(
                    {
                        "revision_id": revision_id,
                        "location": revision["location"],
                        "forecast_date": revision["forecast_date"],
                        "forecast_issue_ts": issue,
                        "prior_forecast_temperature": prior_temp,
                        "forecast_temperature": current_temp,
                        "forecast_revision": current_temp - prior_temp,
                        "event_ticker": contract["event_ticker"],
                        "market_ticker": contract["market_ticker"],
                        "contract_type": contract["contract_type"],
                        "comparison_operator": contract["comparison_operator"],
                        "threshold_value": contract["threshold_value"],
                        "threshold_upper_value": contract["threshold_upper_value"],
                        "horizon": horizon,
                        "target_ts": target,
                        "quote_ts": quote["_ts"],
                        "quote_delay_minutes": (quote["_ts"] - target).total_seconds()
                        / 60,
                        "midpoint": quote["market_mid"],
                        "midpoint_change": midpoint_change,
                        "microprice_change": _change(
                            quote.get("market_microprice"), pre.get("market_microprice")
                        ),
                        "spread_change": _change(
                            quote.get("market_spread"), pre.get("market_spread")
                        ),
                        "top_depth": quote_depth,
                        "depth_change": None
                        if pre_depth is None or quote_depth is None
                        else quote_depth - pre_depth,
                        "depth_source": "known"
                        if quote_depth is not None
                        else "missing",
                        "expected_direction": expected_direction,
                        "moved_in_forecast_direction": None
                        if horizon == "pre" or expected_direction == 0
                        else midpoint_change * expected_direction > 0,
                        "direction_adjusted_midpoint_change": None
                        if horizon == "pre" or expected_direction == 0
                        else midpoint_change * expected_direction,
                        "forecast_event_indicator": probability,
                        "forecast_model_probability": estimate.probability,
                        "forecast_error_sample_size": estimate.sample_size,
                        "forecast_probability_source": estimate.source,
                        "forecast_model_yes_edge_after_fees": yes_edge,
                        "forecast_model_no_edge_after_fees": no_edge,
                    }
                )
    if not results:
        return pl.DataFrame()
    output = pl.DataFrame(results)
    output = _add_partition_changes(output)
    return _add_incorporation_time(output, min_incorporation_move_cents)


def _probability_estimate(
    model: EmpiricalForecastErrorModel | None,
    contract: dict[str, Any],
    temperature: float,
    issue_ts: Any,
    forecast_date: Any,
    forecast_revision: float,
) -> ProbabilityEstimate:
    if model is None:
        return ProbabilityEstimate(None, 0, "no_observations_supplied")
    return model.estimate(
        contract,
        forecast_temperature=temperature,
        forecast_issue_ts=issue_ts,
        forecast_date=forecast_date,
        forecast_revision=forecast_revision,
    )


def _change(value: Any, baseline: Any) -> float | None:
    return None if value is None or baseline is None else float(value) - float(baseline)


def _top_depth(row: dict[str, Any]) -> float | None:
    bid = row.get("yes_bid_depth_1")
    ask = row.get("yes_ask_depth_1")
    return None if bid is None or ask is None else float(bid) + float(ask)


def _add_partition_changes(df: pl.DataFrame) -> pl.DataFrame:
    totals = df.group_by(["revision_id", "event_ticker", "horizon"]).agg(
        pl.col("midpoint").sum().alias("partition_mid_sum"),
        pl.len().alias("partition_observed_legs"),
    )
    output = df.join(totals, on=["revision_id", "event_ticker", "horizon"], how="left")
    output = output.with_columns(
        pl.when(pl.col("partition_observed_legs") == 6)
        .then(pl.col("midpoint") / pl.col("partition_mid_sum"))
        .alias("partition_probability"),
        pl.when(pl.col("partition_observed_legs") == 6)
        .then(pl.col("partition_mid_sum"))
        .alias("complete_partition_mid_sum"),
    )
    pre = output.filter(pl.col("horizon") == "pre").select(
        "revision_id",
        "market_ticker",
        pl.col("complete_partition_mid_sum").alias("pre_partition_mid_sum"),
        pl.col("partition_probability").alias("pre_partition_probability"),
    )
    return output.join(
        pre, on=["revision_id", "market_ticker"], how="left"
    ).with_columns(
        (pl.col("complete_partition_mid_sum") - pl.col("pre_partition_mid_sum")).alias(
            "partition_mid_sum_change"
        ),
        (pl.col("partition_probability") - pl.col("pre_partition_probability")).alias(
            "partition_probability_change"
        ),
    )


def _add_incorporation_time(df: pl.DataFrame, minimum_move: float) -> pl.DataFrame:
    incorporation = (
        df.filter(
            (pl.col("horizon") != "pre")
            & (pl.col("expected_direction") != 0)
            & (pl.col("midpoint_change") * pl.col("expected_direction") >= minimum_move)
        )
        .group_by(["revision_id", "market_ticker"])
        .agg(
            ((pl.col("quote_ts") - pl.col("forecast_issue_ts")).dt.total_seconds() / 60)
            .min()
            .alias("incorporation_minutes")
        )
    )
    return df.join(incorporation, on=["revision_id", "market_ticker"], how="left")


def summarize_forecast_revision_event_study(df: pl.DataFrame) -> pl.DataFrame:
    if len(df) == 0:
        return df
    return (
        df.filter(pl.col("horizon") != "pre")
        .group_by("horizon")
        .agg(
            pl.col("revision_id").n_unique().alias("revisions"),
            pl.len().alias("market_observations"),
            pl.col("midpoint_change").mean().alias("mean_midpoint_change"),
            pl.col("microprice_change").mean().alias("mean_microprice_change"),
            pl.col("spread_change").mean().alias("mean_spread_change"),
            pl.col("depth_change").mean().alias("mean_depth_change"),
            pl.col("moved_in_forecast_direction").mean().alias("directional_hit_rate"),
            pl.col("direction_adjusted_midpoint_change")
            .mean()
            .alias("mean_direction_adjusted_midpoint_change"),
            pl.col("incorporation_minutes")
            .median()
            .alias("median_incorporation_minutes"),
            pl.col("quote_delay_minutes").median().alias("median_quote_delay_minutes"),
        )
        .sort(
            pl.col("horizon").replace_strict(
                {"first_post": 0, "1m": 1, "5m": 5, "15m": 15, "30m": 30}
            )
        )
    )

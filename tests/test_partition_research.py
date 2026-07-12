from datetime import datetime, timedelta

import polars as pl

from eventmm.backtest.fees import FeeModel
from eventmm.research.forecast_revisions import add_forecast_revision_features
from eventmm.research.partitions import (
    build_monotonicity_violations,
    build_partition_features,
    simulate_partition_basket,
)


def _partition() -> pl.DataFrame:
    ts = datetime(2026, 7, 1, 12)
    return pl.DataFrame(
        {
            "event_ticker": ["EVENT"] * 6,
            "market_ticker": [f"M{i}" for i in range(6)],
            "as_of_ts": [ts + timedelta(seconds=i) for i in range(6)],
            "contract_type": [
                "threshold",
                "range",
                "range",
                "range",
                "range",
                "threshold",
            ],
            "comparison_operator": ["<", "range", "range", "range", "range", ">"],
            "threshold_value": [70, 70, 72, 74, 76, 78],
            "best_yes_bid": [9, 14, 14, 14, 14, 29],
            "best_yes_ask": [10, 15, 15, 15, 15, 30],
            "best_no_bid": [90, 85, 85, 85, 85, 70],
            "best_no_ask": [91, 86, 86, 86, 86, 71],
            "market_mid": [9.5, 14.5, 14.5, 14.5, 14.5, 29.5],
            "market_microprice": [9.5, 14.5, 14.5, 14.5, 14.5, 29.5],
            "market_spread": [1] * 6,
            "market_depth_imbalance": [0.0] * 6,
            "yes_ask_depth_1": [2] * 6,
            "no_ask_depth_1": [2] * 6,
        }
    ).with_columns(pl.col("as_of_ts").dt.truncate("1m").alias("quote_bucket"))


def test_partition_features_include_fees_and_depth_source():
    features = build_partition_features(
        _partition(), fee_model=FeeModel(include_fees=False)
    )
    assert features["partition_all_legs_present"][0]
    assert features["partition_sum_yes_ask_cents"][0] == 100
    assert features["long_yes_net_edge_cents"][0] == 0
    assert features["depth_source"][0] == "known"


def test_atomic_and_partial_basket_simulation_track_depth():
    partition = _partition()
    atomic = simulate_partition_basket(
        partition,
        side="yes",
        mode="all_or_none",
        fee_model=FeeModel(include_fees=False),
    )
    assert atomic.complete
    assert atomic.filled_legs == 6
    assert atomic.known_depth_fills == 6
    assert all(fill.depth_source == "known" for fill in atomic.fills)

    shallow = partition.with_columns(
        pl.when(pl.col("market_ticker") == "M0")
        .then(0)
        .otherwise(pl.col("yes_ask_depth_1"))
        .alias("yes_ask_depth_1")
    )
    atomic_failed = simulate_partition_basket(
        shallow, side="yes", mode="all_or_none", fee_model=FeeModel(include_fees=False)
    )
    partial = simulate_partition_basket(
        shallow, side="yes", mode="partial", fee_model=FeeModel(include_fees=False)
    )
    assert atomic_failed.filled_legs == 0
    assert partial.filled_legs == 5
    assert partial.guaranteed_pnl_cents is None


def test_monotonicity_and_forecast_revision_features():
    ts = datetime(2026, 7, 1, 12)
    tails = pl.DataFrame(
        {
            "event_ticker": ["E", "E"],
            "market_ticker": ["LOW", "HIGH"],
            "as_of_ts": [ts, ts],
            "contract_type": ["threshold", "threshold"],
            "comparison_operator": [">", ">"],
            "threshold_value": [80, 85],
            "best_yes_bid": [30, 41],
            "best_yes_ask": [31, 42],
        }
    )
    assert len(build_monotonicity_violations(tails)) == 1

    revisions = add_forecast_revision_features(
        pl.DataFrame(
            {
                "location": ["NYC", "NYC", "NYC"],
                "forecast_date": ["2026-07-02"] * 3,
                "forecast_issue_ts": [ts, ts, ts + timedelta(hours=1)],
                "forecast_temperature": [79, 80, 82],
            }
        )
    )
    assert revisions["forecast_revision"].to_list() == [None, 2]

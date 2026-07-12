from datetime import date, datetime, timedelta, timezone

import polars as pl

from eventmm.backtest.fees import FeeModel
from eventmm.research.forecast_event_study import (
    build_forecast_revision_event_study,
    summarize_forecast_revision_event_study,
)


def test_forecast_revision_event_study_aligns_quotes_and_metrics():
    issue = datetime(2026, 7, 2, 12, tzinfo=timezone.utc)
    forecast_rows = [
        {
            "location": "NYC",
            "forecast_date": date(2026, 6, day),
            "forecast_issue_ts": datetime(2026, 6, day - 1, 12, tzinfo=timezone.utc),
            "forecast_temperature": 80.0,
        }
        for day in range(20, 30)
    ]
    for issued, temperatures in [
        (issue - timedelta(hours=1), [79, 80]),
        (issue, [81, 82]),
    ]:
        for temperature in temperatures:
            forecast_rows.append(
                {
                    "location": "NYC",
                    "forecast_date": date(2026, 7, 3),
                    "forecast_issue_ts": issued,
                    "forecast_temperature": temperature,
                }
            )
    quote_times = [
        issue - timedelta(minutes=5),
        issue + timedelta(seconds=30),
        issue + timedelta(minutes=5),
        issue + timedelta(minutes=15),
        issue + timedelta(minutes=30),
    ]
    quotes = pl.DataFrame(
        {
            "market_ticker": ["UPPER"] * 5,
            "event_ticker": ["EVENT"] * 5,
            "location": ["NYC"] * 5,
            "contract_date": [date(2026, 7, 3)] * 5,
            "contract_type": ["threshold"] * 5,
            "comparison_operator": [">"] * 5,
            "threshold_value": [81.0] * 5,
            "threshold_upper_value": [None] * 5,
            "as_of_ts": quote_times,
            "market_mid": [40.0, 42.0, 45.0, 47.0, 50.0],
            "market_microprice": [40.5, 42.5, 45.5, 47.5, 50.5],
            "market_spread": [2.0, 2.0, 1.0, 1.0, 1.0],
            "best_yes_ask": [41.0, 43.0, 46.0, 48.0, 51.0],
            "best_no_ask": [61.0, 59.0, 56.0, 54.0, 51.0],
            "yes_bid_depth_1": [5.0] * 5,
            "yes_ask_depth_1": [5.0, 6.0, 7.0, 8.0, 9.0],
        }
    )
    result = build_forecast_revision_event_study(
        quotes,
        pl.DataFrame(forecast_rows),
        pl.DataFrame(
            {
                "location": ["NYC"] * 10,
                "date": [date(2026, 6, day) for day in range(20, 30)],
                "value": [80.0] * 10,
            }
        ),
        max_horizon_lag_minutes=2,
        fee_model=FeeModel(include_fees=False),
    )

    assert set(result["horizon"].to_list()) == {"pre", "first_post", "5m", "15m", "30m"}
    first_post = result.filter(pl.col("horizon") == "first_post").row(0, named=True)
    assert first_post["midpoint_change"] == 2
    assert first_post["microprice_change"] == 2
    assert first_post["depth_change"] == 1
    assert first_post["depth_source"] == "known"
    assert first_post["moved_in_forecast_direction"]
    assert first_post["forecast_model_probability"] == 10.5 / 11
    assert first_post["forecast_error_sample_size"] == 10
    assert first_post["forecast_model_yes_edge_after_fees"] == 10.5 / 11 * 100 - 43
    assert first_post["incorporation_minutes"] == 0.5
    assert result["partition_probability_change"].null_count() == len(result)

    summary = summarize_forecast_revision_event_study(result)
    assert summary["revisions"].sum() == 4


def test_forecast_probability_does_not_use_target_date_observation():
    issue = datetime(2026, 7, 2, 12, tzinfo=timezone.utc)
    forecasts = pl.DataFrame(
        [
            {
                "location": "NYC",
                "forecast_date": date(2026, 6, day),
                "forecast_issue_ts": datetime(
                    2026, 6, day - 1, 12, tzinfo=timezone.utc
                ),
                "forecast_temperature": 80.0,
            }
            for day in range(20, 30)
        ]
        + [
            {
                "location": "NYC",
                "forecast_date": date(2026, 7, 3),
                "forecast_issue_ts": issue,
                "forecast_temperature": 82.0,
            }
        ]
    )
    observations = pl.DataFrame(
        {
            "location": ["NYC"] * 11,
            "date": [date(2026, 6, day) for day in range(20, 30)] + [date(2026, 7, 3)],
            "value": [80.0] * 10 + [0.0],
        }
    )
    from eventmm.research.forecast_error_model import (
        EmpiricalForecastErrorModel,
        build_forecast_error_samples,
    )

    model = EmpiricalForecastErrorModel(
        build_forecast_error_samples(forecasts, observations)
    )
    estimate = model.estimate(
        {
            "location": "NYC",
            "contract_type": "threshold",
            "comparison_operator": ">",
            "threshold_value": 81.0,
        },
        forecast_temperature=82,
        forecast_issue_ts=issue,
        forecast_date=date(2026, 7, 3),
    )

    assert estimate.sample_size == 10
    assert estimate.probability == 10.5 / 11

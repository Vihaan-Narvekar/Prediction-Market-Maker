from datetime import datetime

import polars as pl
import pytest

from eventmm.datasets.joins import asof_join_market_weather
from eventmm.datasets.validation import (
    DatasetValidationError,
    validate_no_future_leakage,
)


def test_asof_join_uses_latest_prior_forecast():
    market_features = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "as_of_ts": [datetime(2026, 6, 26, 10)],
            "market_mid": [62.0],
        }
    )
    contracts = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "location": ["NYC"],
            "contract_date": ["2026-06-26"],
            "threshold_value": [85.0],
        }
    )
    forecasts = pl.DataFrame(
        {
            "location": ["NYC", "NYC"],
            "forecast_date": ["2026-06-26", "2026-06-26"],
            "forecast_issue_ts": [datetime(2026, 6, 26, 8), datetime(2026, 6, 26, 11)],
            "forecast_temperature": [86, 88],
            "source": ["nws_api", "nws_api"],
        }
    )

    joined = asof_join_market_weather(market_features, forecasts, contracts)

    assert joined["forecast_temperature"][0] == 86


def test_observation_join_uses_daily_max_temperature():
    market_features = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "as_of_ts": [datetime(2026, 6, 26, 10)],
        }
    )
    contracts = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "location": ["NYC"],
            "contract_date": ["2026-06-26"],
        }
    )
    forecasts = pl.DataFrame(
        {
            "location": ["NYC"],
            "forecast_date": ["2026-06-26"],
            "forecast_issue_ts": [datetime(2026, 6, 26, 8)],
            "forecast_temperature": [86],
            "source": ["nws_api"],
        }
    )
    observations = pl.DataFrame(
        {
            "location": ["NYC", "NYC"],
            "station_id": ["S1", "S2"],
            "date": ["2026-06-26", "2026-06-26"],
            "value": [83.0, 87.0],
        }
    )

    joined = asof_join_market_weather(
        market_features, forecasts, contracts, observations=observations
    )

    assert joined["observed_temperature"][0] == 87.0
    assert joined["observation_station_id"][0] == "S2"


def test_label_observed_value_fills_missing_observed_temperature():
    market_features = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "as_of_ts": [datetime(2026, 6, 26, 10)],
        }
    )
    contracts = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "location": ["NYC"],
            "contract_date": ["2026-06-26"],
        }
    )
    forecasts = pl.DataFrame(
        {
            "location": ["NYC"],
            "forecast_date": ["2026-06-26"],
            "forecast_issue_ts": [datetime(2026, 6, 26, 8)],
            "forecast_temperature": [86],
            "source": ["nws_api"],
        }
    )
    labels = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "label": [1],
            "observed_value": [88.0],
        }
    )

    joined = asof_join_market_weather(
        market_features, forecasts, contracts, labels=labels
    )

    assert joined["observed_temperature"][0] == 88.0


def test_validate_no_future_leakage_raises():
    df = pl.DataFrame(
        {
            "market_ticker": ["M1"],
            "as_of_ts": [datetime(2026, 6, 26, 10)],
            "forecast_issue_ts": [datetime(2026, 6, 26, 11)],
        }
    )

    with pytest.raises(DatasetValidationError):
        validate_no_future_leakage(df)

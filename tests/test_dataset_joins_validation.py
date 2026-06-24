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

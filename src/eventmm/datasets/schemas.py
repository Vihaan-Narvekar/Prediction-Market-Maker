from datetime import datetime

from pydantic import BaseModel


class DatasetRow(BaseModel):
    market_ticker: str
    event_ticker: str | None = None
    series_ticker: str | None = None

    as_of_ts: datetime
    close_time: datetime | None = None
    expiration_time: datetime | None = None
    settlement_time: datetime | None = None

    market_mid: float | None = None
    market_microprice: float | None = None
    market_spread: float | None = None
    market_depth_imbalance: float | None = None

    contract_type: str
    contract_location: str | None = None
    contract_date: datetime | None = None
    threshold_value: float | None = None
    threshold_unit: str | None = None
    comparison_operator: str | None = None

    external_value: float | None = None
    external_forecast_value: float | None = None
    external_observed_value: float | None = None
    external_source: str | None = None

    resolved_outcome: str | None = None
    label: int | None = None

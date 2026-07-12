from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class MarketDataEvent:
    ts: datetime
    market_ticker: str
    best_yes_bid: float | None
    best_yes_ask: float | None
    market_mid: float | None
    market_microprice: float | None
    spread: float | None
    depth_imbalance: float | None
    yes_bid_depth: int | None = None
    yes_ask_depth: int | None = None
    no_bid_depth: int | None = None
    no_ask_depth: int | None = None


@dataclass(frozen=True)
class ForecastEvent:
    ts: datetime
    location: str
    forecast_valid_ts: datetime
    forecast_temperature: float
    forecast_issue_ts: datetime


@dataclass(frozen=True)
class SignalEvent:
    ts: datetime
    market_ticker: str
    p_yes: float
    fair_value_cents: float
    edge_to_mid: float
    buy_yes_edge: float | None
    sell_yes_edge: float | None


@dataclass(frozen=True)
class OrderEvent:
    ts: datetime
    market_ticker: str
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    order_type: Literal["marketable_limit", "passive_limit"]
    price_cents: float
    quantity: int


@dataclass(frozen=True)
class FillEvent:
    ts: datetime
    market_ticker: str
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    price_cents: float
    quantity: int
    fee_cents: float
    liquidity: Literal["taker", "maker", "simulated"]
    requested_quantity: int | None = None
    depth_source: Literal["known", "assumed"] = "assumed"

    def to_row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SettlementEvent:
    ts: datetime
    market_ticker: str
    label: int

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args

from eventmm.utils.decimal import Money, Price, Quantity, to_decimal


@dataclass(frozen=True)
class DecimalEvent:
    """Normalize legacy numeric callers at the domain boundary."""

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None and (
                field.type is Decimal or Decimal in get_args(field.type)
            ):
                object.__setattr__(self, field.name, to_decimal(value))


@dataclass(frozen=True)
class MarketDataEvent(DecimalEvent):
    ts: datetime
    market_ticker: str
    best_yes_bid: Price | None
    best_yes_ask: Price | None
    market_mid: Price | None
    market_microprice: Price | None
    spread: Price | None
    depth_imbalance: float | None
    yes_bid_depth: Quantity | None = None
    yes_ask_depth: Quantity | None = None
    no_bid_depth: Quantity | None = None
    no_ask_depth: Quantity | None = None


@dataclass(frozen=True)
class ForecastEvent:
    ts: datetime
    location: str
    forecast_valid_ts: datetime
    forecast_temperature: float
    forecast_issue_ts: datetime


@dataclass(frozen=True)
class SignalEvent(DecimalEvent):
    ts: datetime
    market_ticker: str
    p_yes: float
    fair_value_cents: Price
    edge_to_mid: Price
    buy_yes_edge: Price | None
    sell_yes_edge: Price | None


@dataclass(frozen=True)
class OrderEvent(DecimalEvent):
    ts: datetime
    market_ticker: str
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    order_type: Literal["marketable_limit", "passive_limit"]
    price_cents: Price
    quantity: Quantity


@dataclass(frozen=True)
class FillEvent(DecimalEvent):
    ts: datetime
    market_ticker: str
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    price_cents: Price
    quantity: Quantity
    fee_cents: Money
    liquidity: Literal["taker", "maker", "simulated"]
    requested_quantity: Quantity | None = None
    depth_source: Literal["known", "assumed"] = "assumed"

    def to_row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SettlementEvent:
    ts: datetime
    market_ticker: str
    label: int

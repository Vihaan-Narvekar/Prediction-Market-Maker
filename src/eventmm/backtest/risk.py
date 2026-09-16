from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from eventmm.utils.decimal import to_decimal


def within_position_limit(
    current_position: Decimal, order_quantity: Decimal, max_position: Decimal
) -> bool:
    return abs(to_decimal(current_position) + to_decimal(order_quantity)) <= to_decimal(
        max_position
    )


def signed_yes_equivalent(
    *,
    side: Literal["yes", "no"],
    action: Literal["buy", "sell"],
    quantity: Decimal,
) -> Decimal:
    quantity = to_decimal(quantity)
    return quantity if (side, action) in {("yes", "buy"), ("no", "sell")} else -quantity


@dataclass
class ExposureLimits:
    max_market_position: Decimal
    max_event_exposure: Decimal
    market_positions: dict[str, Decimal] = field(default_factory=dict)
    event_exposures: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.max_market_position = to_decimal(self.max_market_position)
        self.max_event_exposure = to_decimal(self.max_event_exposure)
        self.market_positions = {
            key: to_decimal(value) for key, value in self.market_positions.items()
        }
        self.event_exposures = {
            key: to_decimal(value) for key, value in self.event_exposures.items()
        }

    def allows(
        self, *, market_ticker: str, event_ticker: str, signed_quantity: Decimal
    ) -> bool:
        signed_quantity = to_decimal(signed_quantity)
        market = self.market_positions.get(market_ticker, 0) + signed_quantity
        event = self.event_exposures.get(event_ticker, 0) + abs(signed_quantity)
        return (
            abs(market) <= self.max_market_position and event <= self.max_event_exposure
        )

    def record(
        self, *, market_ticker: str, event_ticker: str, signed_quantity: Decimal
    ) -> None:
        signed_quantity = to_decimal(signed_quantity)
        if not self.allows(
            market_ticker=market_ticker,
            event_ticker=event_ticker,
            signed_quantity=signed_quantity,
        ):
            raise ValueError("Exposure limit exceeded.")
        self.market_positions[market_ticker] = (
            self.market_positions.get(market_ticker, 0) + signed_quantity
        )
        self.event_exposures[event_ticker] = self.event_exposures.get(
            event_ticker, 0
        ) + abs(signed_quantity)

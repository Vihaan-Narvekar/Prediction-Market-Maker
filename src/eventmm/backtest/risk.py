from dataclasses import dataclass, field
from typing import Literal


def within_position_limit(
    current_position: int, order_quantity: int, max_position: int
) -> bool:
    return abs(current_position + order_quantity) <= max_position


def signed_yes_equivalent(
    *,
    side: Literal["yes", "no"],
    action: Literal["buy", "sell"],
    quantity: int,
) -> int:
    return quantity if (side, action) in {("yes", "buy"), ("no", "sell")} else -quantity


@dataclass
class ExposureLimits:
    max_market_position: int
    max_event_exposure: int
    market_positions: dict[str, int] = field(default_factory=dict)
    event_exposures: dict[str, int] = field(default_factory=dict)

    def allows(
        self, *, market_ticker: str, event_ticker: str, signed_quantity: int
    ) -> bool:
        market = self.market_positions.get(market_ticker, 0) + signed_quantity
        event = self.event_exposures.get(event_ticker, 0) + abs(signed_quantity)
        return (
            abs(market) <= self.max_market_position and event <= self.max_event_exposure
        )

    def record(
        self, *, market_ticker: str, event_ticker: str, signed_quantity: int
    ) -> None:
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

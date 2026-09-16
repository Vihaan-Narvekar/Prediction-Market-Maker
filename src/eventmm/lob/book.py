from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from eventmm.lob.normalization import (
    infer_no_asks_from_yes_bids,
    infer_yes_asks_from_no_bids,
)
from eventmm.utils.decimal import to_decimal


@dataclass
class BinaryOrderBook:
    market_ticker: str
    yes_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    no_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    last_seq: int | None = None
    last_update_ts: datetime | None = None

    def __post_init__(self) -> None:
        self.yes_bids = {to_decimal(p): to_decimal(q) for p, q in self.yes_bids.items()}
        self.no_bids = {to_decimal(p): to_decimal(q) for p, q in self.no_bids.items()}

    def best_yes_bid(self) -> Decimal | None:
        return max(self.yes_bids) if self.yes_bids else None

    def best_no_bid(self) -> Decimal | None:
        return max(self.no_bids) if self.no_bids else None

    def yes_asks(self) -> dict[Decimal, Decimal]:
        return infer_yes_asks_from_no_bids(self.no_bids)

    def no_asks(self) -> dict[Decimal, Decimal]:
        return infer_no_asks_from_yes_bids(self.yes_bids)

    def best_yes_ask(self) -> Decimal | None:
        asks = self.yes_asks()
        return min(asks) if asks else None

    def best_no_ask(self) -> Decimal | None:
        asks = self.no_asks()
        return min(asks) if asks else None

    def yes_spread(self) -> Decimal | None:
        bid = self.best_yes_bid()
        ask = self.best_yes_ask()
        if bid is None or ask is None:
            return None
        return ask - bid

    def yes_midpoint(self) -> Decimal | None:
        bid = self.best_yes_bid()
        ask = self.best_yes_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    def apply_snapshot(
        self,
        yes_bids: dict[Decimal, Decimal],
        no_bids: dict[Decimal, Decimal],
        seq: int | None = None,
        ts: datetime | None = None,
    ) -> None:
        self.yes_bids = {to_decimal(p): to_decimal(q) for p, q in yes_bids.items()}
        self.no_bids = {to_decimal(p): to_decimal(q) for p, q in no_bids.items()}
        self.last_seq = seq
        self.last_update_ts = ts
        self.validate()

    def apply_delta(
        self,
        side: str,
        price_cents: Decimal,
        delta_qty: Decimal,
        seq: int,
        ts: datetime | None = None,
    ) -> None:
        if side not in {"yes", "no"}:
            raise ValueError(f"Unsupported book side: {side}")
        if self.last_seq is not None and seq <= self.last_seq:
            return

        price_cents = to_decimal(price_cents)
        delta_qty = to_decimal(delta_qty)
        book = self.yes_bids if side == "yes" else self.no_bids
        new_qty = book.get(price_cents, Decimal("0")) + delta_qty

        if new_qty <= 0:
            book.pop(price_cents, None)
        else:
            book[price_cents] = new_qty

        self.last_seq = seq
        self.last_update_ts = ts
        self.validate()

    def validate(self) -> None:
        for price in list(self.yes_bids) + list(self.no_bids):
            if not to_decimal(price).is_finite() or price < 0 or price > 100:
                raise ValueError(f"Invalid price level: {price}")

        for quantity in list(self.yes_bids.values()) + list(self.no_bids.values()):
            if not to_decimal(quantity).is_finite() or quantity < 0:
                raise ValueError(f"Negative quantity: {quantity}")

        bid = self.best_yes_bid()
        ask = self.best_yes_ask()
        if bid is not None and ask is not None and bid > ask:
            raise ValueError(
                f"Crossed YES book for {self.market_ticker}: bid={bid}, ask={ask}"
            )

"""Normalize fixed-point market metadata without relying on legacy cent fields."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Literal

from eventmm.utils.decimal import to_decimal


@dataclass(frozen=True)
class PriceRange:
    """A dollar-denominated price grid, anchored at start (end inclusive)."""

    start: Decimal
    end: Decimal
    step: Decimal

    def __post_init__(self) -> None:
        for name in ("start", "end", "step"):
            object.__setattr__(self, name, to_decimal(getattr(self, name)))
        if not 0 <= self.start < self.end <= 1 or self.step <= 0:
            raise ValueError("Invalid price range")

    def contains(self, price: Decimal) -> bool:
        price = to_decimal(price)
        return self.start <= price <= self.end and (price - self.start) % self.step == 0


def parse_price_ranges(market: dict[str, Any]) -> list[PriceRange]:
    return [PriceRange(**band) for band in market.get("price_ranges", [])]


def snap_price(
    price_dollars: Decimal,
    ranges: list[PriceRange],
    direction: Literal["down", "up"],
) -> Decimal:
    """Snap across bands/gaps using the supplied grid, never a structure label."""
    price = to_decimal(price_dollars)
    if direction not in {"down", "up"}:
        raise ValueError("Expected down or up")
    candidates = []
    for band in ranges:
        target = min(price, band.end) if direction == "down" else max(price, band.start)
        rounding = ROUND_FLOOR if direction == "down" else ROUND_CEILING
        ticks = ((target - band.start) / band.step).to_integral_value(rounding=rounding)
        candidate = band.start + ticks * band.step
        if band.contains(candidate) and (
            candidate <= price if direction == "down" else candidate >= price
        ):
            candidates.append(candidate)
    if not candidates:
        raise ValueError("No valid price in the requested direction")
    return max(candidates) if direction == "down" else min(candidates)


def normalize_market(market: dict[str, Any]) -> dict[str, Any]:
    """Keep API units/names, decoding dollars and fractional counts losslessly.

    Quantity aliases support existing universe consumers. Fixed-point fields take
    precedence even when zero. No rounded cent price aliases are synthesized.
    """
    result = dict(market)
    for name, value in market.items():
        if value is not None and (name.endswith("_dollars") or name.endswith("_fp")):
            result[name] = to_decimal(value)
            if name.endswith("_fp"):
                result[name.removesuffix("_fp")] = result[name]
    if "price_ranges" in market:
        result["price_ranges"] = [
            {"start": band.start, "end": band.end, "step": band.step}
            for band in parse_price_ranges(market)
        ]
    return result

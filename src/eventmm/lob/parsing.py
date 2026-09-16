from decimal import Decimal
from typing import Any

from eventmm.utils.decimal import dollars_to_cents, quantity_to_decimal


def parse_book_levels(levels: list[list[Any]]) -> dict[Decimal, Decimal]:
    parsed: dict[Decimal, Decimal] = {}

    for level in levels:
        if len(level) != 2:
            raise ValueError(f"Book level must have price and quantity: {level!r}")

        price_cents = dollars_to_cents(level[0])
        quantity = quantity_to_decimal(level[1])

        if price_cents < 0 or price_cents > 100:
            raise ValueError(f"Invalid price_cents={price_cents}")
        if quantity < 0:
            raise ValueError(f"Negative quantity={quantity}")

        parsed[price_cents] = quantity

    return parsed


def parse_rest_orderbook(
    raw: dict[str, Any],
) -> tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]:
    orderbook = raw.get("orderbook_fp", raw.get("orderbook", raw))

    yes_levels = orderbook.get("yes_dollars_fp", orderbook.get("yes_dollars", [])) or []
    no_levels = orderbook.get("no_dollars_fp", orderbook.get("no_dollars", [])) or []

    return parse_book_levels(yes_levels), parse_book_levels(no_levels)

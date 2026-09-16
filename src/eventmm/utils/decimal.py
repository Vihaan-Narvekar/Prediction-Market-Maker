"""Exact financial values. Internal research prices/money retain cent units.

API fields ending in ``_dollars`` and price-range bands remain in dollars.
Only explicit unit conversions cross this boundary; neither conversion rounds.
"""

from decimal import Decimal
from typing import TypeAlias

Price: TypeAlias = Decimal
Quantity: TypeAlias = Decimal
Money: TypeAlias = Decimal
DecimalInput: TypeAlias = str | int | float | Decimal


def to_decimal(value: DecimalInput) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"Expected a finite decimal: {value!r}")
    return result


def dollars_to_cents(price: DecimalInput) -> Price:
    return to_decimal(price) * 100


def cents_to_dollars(price: DecimalInput) -> Price:
    return to_decimal(price) / 100


def quantity_to_decimal(quantity: DecimalInput) -> Quantity:
    return to_decimal(quantity)


def decimal_json(value: object) -> str:
    """Encode decimals losslessly as JSON strings, rejecting other unknown types."""
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Cannot serialize {type(value).__name__}")

from decimal import Decimal, ROUND_HALF_UP


def dollars_to_cents(price: str | int | float | Decimal) -> int:
    value = Decimal(str(price))
    return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quantity_to_decimal(quantity: str | int | float | Decimal) -> Decimal:
    return Decimal(str(quantity))

from decimal import Decimal


def yes_settlement_value_cents(label: int) -> Decimal:
    return Decimal("100") if label == 1 else Decimal("0")


def no_settlement_value_cents(label: int) -> Decimal:
    return Decimal("100") if label == 0 else Decimal("0")

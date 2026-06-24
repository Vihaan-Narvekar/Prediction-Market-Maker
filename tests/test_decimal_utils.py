from decimal import Decimal

from eventmm.utils.decimal import dollars_to_cents, quantity_to_decimal


def test_dollars_to_cents_rounds_half_up():
    assert dollars_to_cents("0.425") == 43


def test_quantity_to_decimal():
    assert quantity_to_decimal("13.00") == Decimal("13.00")

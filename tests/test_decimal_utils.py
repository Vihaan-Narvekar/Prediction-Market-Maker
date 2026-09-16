from decimal import Decimal

from eventmm.utils.decimal import dollars_to_cents, quantity_to_decimal


def test_dollars_to_cents_preserves_subpenny_precision():
    assert dollars_to_cents("0.425") == Decimal("42.5")


def test_quantity_to_decimal():
    assert quantity_to_decimal("13.00") == Decimal("13.00")

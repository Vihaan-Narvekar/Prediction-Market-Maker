from decimal import Decimal

from eventmm.utils.decimal import to_decimal


def probability_to_yes_price_cents(probability: float | Decimal) -> Decimal:
    return 100 * to_decimal(probability)

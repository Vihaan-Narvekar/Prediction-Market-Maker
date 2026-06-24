def yes_settlement_value_cents(label: int) -> int:
    return 100 if label == 1 else 0


def no_settlement_value_cents(label: int) -> int:
    return 100 if label == 0 else 0

from decimal import Decimal


def yes_ask_from_no_bid(no_bid_cents: int) -> int:
    return 100 - no_bid_cents


def no_ask_from_yes_bid(yes_bid_cents: int) -> int:
    return 100 - yes_bid_cents


def infer_yes_asks_from_no_bids(no_bids: dict[int, Decimal]) -> dict[int, Decimal]:
    asks = {yes_ask_from_no_bid(price): qty for price, qty in no_bids.items()}
    return dict(sorted(asks.items()))


def infer_no_asks_from_yes_bids(yes_bids: dict[int, Decimal]) -> dict[int, Decimal]:
    asks = {no_ask_from_yes_bid(price): qty for price, qty in yes_bids.items()}
    return dict(sorted(asks.items()))

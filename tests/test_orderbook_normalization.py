from decimal import Decimal

from eventmm.lob.normalization import (
    infer_yes_asks_from_no_bids,
    no_ask_from_yes_bid,
    yes_ask_from_no_bid,
)


def test_yes_ask_from_no_bid():
    assert yes_ask_from_no_bid(37) == 63


def test_no_ask_from_yes_bid():
    assert no_ask_from_yes_bid(42) == 58


def test_highest_no_bid_becomes_lowest_yes_ask():
    no_bids = {
        30: Decimal("1"),
        35: Decimal("1"),
        40: Decimal("1"),
    }

    asks = infer_yes_asks_from_no_bids(no_bids)

    assert min(asks) == 60
    assert list(asks) == [60, 65, 70]

from decimal import Decimal

from eventmm.lob.parsing import parse_book_levels, parse_rest_orderbook


def test_parse_book_levels():
    levels = [["0.4200", "13.00"], ["0.4400", "2.00"]]
    parsed = parse_book_levels(levels)

    assert parsed[42] == Decimal("13.00")
    assert parsed[44] == Decimal("2.00")


def test_parse_rest_orderbook():
    raw = {
        "orderbook": {
            "yes_dollars": [["0.42", "13"]],
            "no_dollars": [["0.55", "20"]],
        }
    }

    yes_bids, no_bids = parse_rest_orderbook(raw)

    assert yes_bids == {42: Decimal("13")}
    assert no_bids == {55: Decimal("20")}

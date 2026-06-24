from decimal import Decimal

import orjson

from eventmm.schemas.websocket import (
    parse_orderbook_delta,
    parse_orderbook_snapshot,
    parse_ws_message,
)


def test_parse_ws_message():
    assert parse_ws_message(orjson.dumps({"type": "ok"})) == {"type": "ok"}


def test_parse_orderbook_snapshot():
    parsed = parse_orderbook_snapshot(
        {
            "type": "orderbook_snapshot",
            "seq": 7,
            "msg": {
                "market_ticker": "TEST",
                "yes_dollars": [["0.40", "10"]],
                "no_dollars": [["0.55", "20"]],
            },
        }
    )

    assert parsed["seq"] == 7
    assert parsed["yes_bids"] == {40: Decimal("10")}


def test_parse_orderbook_delta():
    parsed = parse_orderbook_delta(
        {
            "type": "orderbook_delta",
            "seq": 8,
            "msg": {
                "market_ticker": "TEST",
                "side": "yes",
                "price_dollars": "0.41",
                "delta_fp": "3",
            },
        }
    )

    assert parsed["price_cents"] == 41
    assert parsed["delta_qty"] == Decimal("3")

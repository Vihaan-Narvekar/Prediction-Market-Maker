from datetime import datetime
from decimal import Decimal
from typing import Any

import orjson

from eventmm.lob.parsing import parse_book_levels
from eventmm.utils.decimal import dollars_to_cents


def parse_ws_message(raw: str | bytes) -> dict[str, Any]:
    return orjson.loads(raw)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def parse_orderbook_snapshot(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg["msg"]
    yes_levels = payload.get("yes_dollars_fp") or payload.get("yes_dollars") or []
    no_levels = payload.get("no_dollars_fp") or payload.get("no_dollars") or []

    return {
        "market_ticker": payload["market_ticker"],
        "seq": msg.get("seq"),
        "yes_bids": parse_book_levels(yes_levels),
        "no_bids": parse_book_levels(no_levels),
        "ts": _parse_ts(payload.get("ts")),
    }


def parse_orderbook_delta(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg["msg"]
    return {
        "market_ticker": payload["market_ticker"],
        "seq": msg["seq"],
        "side": payload["side"],
        "price_cents": dollars_to_cents(payload["price_dollars"]),
        "delta_qty": Decimal(str(payload["delta_fp"])),
        "ts": _parse_ts(payload.get("ts")),
    }

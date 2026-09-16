"""Live state and the fail-closed gate for exposure-increasing actions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from time import monotonic, time
from typing import Any

from eventmm.lob.book import BinaryOrderBook
from eventmm.schemas.market import normalize_market, parse_price_ranges
from eventmm.schemas.websocket import parse_orderbook_delta, parse_orderbook_snapshot
from eventmm.utils.decimal import to_decimal

CHANNEL_TYPES = {
    "orderbook_delta": {"orderbook_snapshot", "orderbook_delta"},
    "user_orders": {"user_order"},
    "fill": {"fill"},
    "market_positions": {"market_position"},
    "market_lifecycle_v2": {
        "market_lifecycle_v2",
        "event_lifecycle",
        "event_fee_update",
    },
    "multivariate_market_lifecycle": {
        "multivariate_market_lifecycle",
        "event_lifecycle",
    },
    "order_group_updates": {"order_group_updates"},
}
DEFAULT_CHANNELS = tuple(CHANNEL_TYPES)
CHANNEL_TYPES["trade"] = {"trade"}
SUPPORTED_CHANNELS = tuple(CHANNEL_TYPES)
PRIVATE_TYPES = {"user_order", "fill", "market_position", "order_group_updates"}


class StreamInvalid(RuntimeError):
    """The stream must be resubscribed and state reconciled."""


class TradingHalted(RuntimeError):
    pass


def decimal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: [[to_decimal(price), to_decimal(quantity)] for price, quantity in value]
        if key in {"yes_dollars_fp", "no_dollars_fp", "yes_dollars", "no_dollars"}
        and value is not None
        else to_decimal(value)
        if value is not None and key.endswith(("_dollars", "_fp"))
        else value
        for key, value in payload.items()
    }


@dataclass
class LiveMarket:
    book: BinaryOrderBook | None = None
    received_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    invalid_reason: str | None = "awaiting snapshot"


class StreamState:
    def __init__(
        self,
        market_tickers: list[str],
        *,
        stale_after: float = 30.0,
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time,
    ):
        if stale_after <= 0:
            raise ValueError("stale_after must be positive")
        self.markets = {ticker: LiveMarket() for ticker in market_tickers}
        self.stale_after = stale_after
        self.clock, self.wall_clock = clock, wall_clock
        self.connected = False
        self.epoch = 0
        self.revision = 0
        self.account_reconciled = False
        self.halt_reason = "disconnected"
        self.subscriptions: dict[int, str] = {}
        self.sequences: dict[int, int] = {}
        self.orders: dict[str, dict] = {}
        self.fills: dict[str, dict] = {}
        self.positions: dict[tuple[int, str], dict] = {}
        self.order_groups: dict[str, dict] = {}
        self.events: dict[str, dict] = {}

    def connect(self) -> None:
        self.disconnect("awaiting subscriptions and reconciliation")
        self.epoch += 1
        self.connected = True
        self.revision = 0
        for market in self.markets.values():
            market.metadata = {}

    def disconnect(self, reason: str = "disconnected") -> None:
        self.connected = False
        self.account_reconciled = False
        self.halt_reason = reason
        self.subscriptions.clear()
        self.sequences.clear()
        for market in self.markets.values():
            market.book = None
            market.received_at = None
            market.invalid_reason = reason

    @property
    def reconciliation_token(self) -> tuple[int, int]:
        """Capture before an authoritative account/metadata reconciliation."""
        return self.epoch, self.revision

    def confirm_reconciled(self, token: tuple[int, int]) -> None:
        """Caller certifies REST/order-response state was reconciled with this stream.

        Subscription acknowledgements and individual updates are NOT a complete
        account snapshot. Tokens reject reconciliation across reconnects or updates.
        The caller must drain/resolve in-flight updates before certification.
        """
        if not self.connected or token != self.reconciliation_token:
            raise TradingHalted("State changed during reconciliation")
        if not set(DEFAULT_CHANNELS).issubset(self.subscriptions.values()):
            raise TradingHalted("Required subscriptions are not acknowledged")
        self.account_reconciled = True

    def reconcile_account(
        self,
        *,
        orders: list[dict],
        positions: list[dict],
        order_groups: list[dict],
        token: tuple[int, int],
    ) -> None:
        """Install caller-reconciled complete account state, then release its gate.

        Group records must include an explicit boolean `blocked` determined by
        reconciliation; unknown group status remains blocked. This method does
        not assume REST responses alone establish a stream-consistent snapshot.
        """
        self.account_reconciled = False
        if not self.connected or token != self.reconciliation_token:
            raise TradingHalted("State changed during reconciliation")
        new_orders = {row["order_id"]: decimal_payload(row) for row in orders}
        new_positions = {
            (
                int(row.get("subaccount", row.get("subaccount_number", 0))),
                row["market_ticker"] if "market_ticker" in row else row["ticker"],
            ): decimal_payload(row)
            for row in positions
        }
        new_groups = {
            row["order_group_id"]: decimal_payload(row) for row in order_groups
        }
        self.confirm_reconciled(token)
        self.orders, self.positions, self.order_groups = (
            new_orders,
            new_positions,
            new_groups,
        )

    def set_market_metadata(
        self, ticker: str, metadata: dict, token: tuple[int, int]
    ) -> None:
        if not self.connected or token != self.reconciliation_token:
            raise TradingHalted("Stale market metadata reconciliation")
        self.markets[ticker].metadata = normalize_market(metadata)

    def _sequence(self, message: dict, channel: str) -> bool:
        sid = message["sid"]
        seq = message.get("seq")
        if seq is None:
            if channel == "orderbook_delta":
                raise StreamInvalid("Book message missing sequence")
            return True
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise StreamInvalid("Invalid sequence")
        previous = self.sequences.get(sid)
        if previous is not None:
            if seq == previous:
                return False
            if seq != previous + 1:
                raise StreamInvalid(
                    f"Sequence gap on subscription {sid}: {previous} -> {seq}"
                )
        self.sequences[sid] = seq
        return True

    def apply(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Apply before invoking downstream handlers. Errors invalidate all state."""
        try:
            return self._apply(message)
        except Exception:
            self.disconnect("invalid stream message; reconnect and reconcile")
            raise

    def _apply(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not self.connected:
            raise StreamInvalid("Message received while disconnected")
        kind = message["type"]
        if kind == "error":
            raise StreamInvalid(f"WebSocket command failed: {message.get('msg')}")
        if kind == "unsubscribed":
            raise StreamInvalid("Required subscription ended")
        if kind == "subscribed":
            payload = message["msg"]
            channel, sid = payload["channel"], payload["sid"]
            if channel not in CHANNEL_TYPES or sid in self.subscriptions:
                raise StreamInvalid("Unexpected subscription acknowledgement")
            self.subscriptions[sid] = channel
            return message
        sid = message.get("sid")
        if kind == "ok" and sid is None:
            return message
        if sid not in self.subscriptions:
            raise StreamInvalid(f"Message for unknown subscription {sid}")
        channel = self.subscriptions[sid]
        if kind != "ok" and kind not in CHANNEL_TYPES[channel]:
            raise StreamInvalid(f"Unexpected {kind} on {channel}")
        if not self._sequence(message, channel):
            return None
        if kind == "ok":
            return message
        payload = decimal_payload(message["msg"])
        if kind in {"orderbook_snapshot", "orderbook_delta"}:
            self._book(message, payload["market_ticker"])
        elif kind == "user_order":
            order_id = payload["order_id"]
            self.orders[order_id] = {**self.orders.get(order_id, {}), **payload}
        elif kind == "fill":
            fill_id = payload["trade_id"]
            if fill_id in self.fills:
                return None
            self.fills[fill_id] = payload
            # Positions come from the authoritative position channel. Do not add
            # fills to positions as well, which would double-count executions.
        elif kind == "market_position":
            key = (
                int(payload.get("subaccount", payload.get("subaccount_number", 0))),
                payload["market_ticker"],
            )
            self.positions[key] = payload
        elif kind == "order_group_updates":
            group_id = payload["order_group_id"]
            group = {**self.order_groups.get(group_id, {}), **payload}
            event = payload["event_type"]
            if event in {"triggered", "deleted"}:
                group["blocked"] = True
            elif event in {"created", "reset"}:
                group["blocked"] = False
            elif event != "limit_updated":
                group["blocked"] = True
            self.order_groups[group_id] = group
        elif kind in {"market_lifecycle_v2", "multivariate_market_lifecycle"}:
            self._lifecycle(payload["market_ticker"], payload)
        elif kind in {"event_lifecycle", "event_fee_update"}:
            event_id = payload["event_ticker"]
            self.events[event_id] = {**self.events.get(event_id, {}), **payload}
            if kind == "event_fee_update":
                self.account_reconciled = False
        if kind in PRIVATE_TYPES or "lifecycle" in kind or kind == "event_fee_update":
            self.revision += 1
        return {**message, "msg": payload}

    def _book(self, message: dict, ticker: str) -> None:
        if ticker not in self.markets:
            raise StreamInvalid(f"Unrequested book {ticker}")
        market = self.markets[ticker]
        if message["type"] == "orderbook_snapshot":
            parsed = parse_orderbook_snapshot(message)
            book = BinaryOrderBook(ticker)
            book.apply_snapshot(
                parsed["yes_bids"],
                parsed["no_bids"],
                seq=parsed["seq"],
                ts=parsed["ts"],
            )
        else:
            if market.book is None or market.invalid_reason:
                raise StreamInvalid(f"Delta before valid snapshot for {ticker}")
            parsed = parse_orderbook_delta(message)
            book = BinaryOrderBook(
                ticker, dict(market.book.yes_bids), dict(market.book.no_bids)
            )
            if not 0 <= parsed["price_cents"] <= 100:
                raise StreamInvalid("Invalid delta price")
            side = book.yes_bids if parsed["side"] == "yes" else book.no_bids
            if side.get(parsed["price_cents"], 0) + parsed["delta_qty"] < 0:
                raise StreamInvalid("Delta would create negative depth")
            # Continuity is tracked per SID above, not per ticker. A shared SID
            # may interleave snapshots/deltas for multiple markets.
            book.apply_delta(
                parsed["side"],
                parsed["price_cents"],
                parsed["delta_qty"],
                parsed["seq"],
                parsed["ts"],
            )
        market.book = book
        market.received_at = self.clock()
        market.invalid_reason = None

    def _lifecycle(self, ticker: str, payload: dict) -> None:
        if ticker not in self.markets:
            return
        market = self.markets[ticker]
        event = payload["event_type"]
        market.metadata.update(normalize_market(payload))
        if event == "activated":
            market.metadata["status"] = "active"
        elif event in {"deactivated", "determined", "settled"}:
            market.metadata["status"] = event
        elif event == "created":
            market.metadata["status"] = "initialized"
        if event != "close_date_updated":
            market.book = None
            market.invalid_reason = f"lifecycle {event}: refresh metadata and snapshot"
        if event not in {
            "created",
            "activated",
            "deactivated",
            "determined",
            "settled",
            "close_date_updated",
        }:
            self.account_reconciled = False
            market.metadata["status"] = "unknown"
        if event in {"metadata_updated", "price_level_structure_updated"}:
            self.account_reconciled = False
            if (
                event == "price_level_structure_updated"
                and "price_ranges" not in payload
            ):
                market.metadata.pop("price_ranges", None)

    def trading_block_reason(
        self, ticker: str, order_group_id: str | None = None
    ) -> str | None:
        if not self.connected:
            return self.halt_reason
        if not set(DEFAULT_CHANNELS).issubset(self.subscriptions.values()):
            return "required subscriptions not acknowledged"
        if not self.account_reconciled:
            return "account reconciliation required"
        market = self.markets.get(ticker)
        if market is None:
            return "market not subscribed"
        if market.invalid_reason or market.book is None:
            return market.invalid_reason or "snapshot missing"
        if (
            market.received_at is None
            or self.clock() - market.received_at >= self.stale_after
        ):
            return "stale market book"
        if market.metadata.get("status") not in {"active", "open"}:
            return "market is not active"
        close = market.metadata.get("close_ts", market.metadata.get("close_time"))
        if close is None:
            return "market close time unknown"
        try:
            if isinstance(close, str):
                close = datetime.fromisoformat(close.replace("Z", "+00:00"))
            if isinstance(close, datetime):
                if close.tzinfo is None:
                    close = close.replace(tzinfo=timezone.utc)
                close = close.timestamp()
            if not isfinite(close):
                return "invalid market close time"
        except (ValueError, TypeError, OverflowError):
            return "invalid market close time"
        if self.wall_clock() >= close:
            return "market closed"
        if not market.metadata.get("price_ranges"):
            return "market price grid unknown"
        try:
            market.book.validate()
            bands = parse_price_ranges(market.metadata)
            if any(
                not any(band.contains(price / 100) for band in bands)
                for price in list(market.book.yes_bids) + list(market.book.no_bids)
            ):
                return "book contains off-grid price"
        except ValueError:
            return "invalid market book or price grid"
        yes_bid, no_bid = market.book.best_yes_bid(), market.book.best_no_bid()
        if yes_bid is None or no_bid is None:
            return "two-sided book required"
        if market.book.yes_spread() == 0:
            return "locked market book"
        if market.book.yes_bids[yes_bid] <= 0 or market.book.no_bids[no_bid] <= 0:
            return "nonpositive top-of-book depth"
        if order_group_id is not None:
            group = self.order_groups.get(order_group_id)
            if group is None or group.get("blocked") is not False:
                return "order group unknown, triggered, or deleted"
        return None

    def require_trading_ready(
        self, ticker: str, order_group_id: str | None = None
    ) -> None:
        reason = self.trading_block_reason(ticker, order_group_id)
        if reason:
            raise TradingHalted(reason)

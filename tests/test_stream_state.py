from decimal import Decimal

import pytest

from eventmm.kalshi.stream_state import (
    DEFAULT_CHANNELS,
    StreamInvalid,
    StreamState,
    TradingHalted,
)


def connected(tickers=None):
    state = StreamState(tickers or ["M"], clock=lambda: 100, wall_clock=lambda: 1000)
    state.connect()
    for sid, channel in enumerate(DEFAULT_CHANNELS, 1):
        state.apply({"type": "subscribed", "msg": {"sid": sid, "channel": channel}})
    return state


def sid_for(state, channel):
    return next(sid for sid, name in state.subscriptions.items() if name == channel)


def snapshot(ticker="M", seq=1):
    return {
        "type": "orderbook_snapshot",
        "sid": 1,
        "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "yes_dollars_fp": [["0.4201", "1.25"]],
            "no_dollars_fp": [["0.5701", "2.50"]],
        },
    }


def delta(ticker="M", seq=2, quantity="0.25"):
    return {
        "type": "orderbook_delta",
        "sid": 1,
        "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "side": "yes",
            "price_dollars": "0.4201",
            "delta_fp": quantity,
        },
    }


def ready(state):
    state.apply(snapshot())
    state.set_market_metadata(
        "M",
        {
            "status": "active",
            "close_ts": 2000,
            "price_ranges": [{"start": "0", "end": "1", "step": "0.0001"}],
        },
        state.reconciliation_token,
    )
    state.reconcile_account(
        orders=[], positions=[], order_groups=[], token=state.reconciliation_token
    )
    state.require_trading_ready("M")


def emit(state, channel, kind, payload, seq=None):
    message = {"type": kind, "sid": sid_for(state, channel), "msg": payload}
    if seq is not None:
        message["seq"] = seq
    return state.apply(message)


def test_trading_requires_ack_snapshot_metadata_and_reconciliation():
    state = StreamState(["M"])
    with pytest.raises(TradingHalted):
        state.require_trading_ready("M")
    state = connected()
    assert state.trading_block_reason("M") == "account reconciliation required"
    ready(state)
    state.disconnect()
    with pytest.raises(TradingHalted):
        state.require_trading_ready("M")
    state.connect()
    assert not state.account_reconciled
    assert state.markets["M"].book is None


def test_sequence_is_per_subscription_not_market():
    state = connected(["M", "N"])
    state.apply(snapshot("M", 10))
    state.apply(snapshot("N", 11))
    state.apply(delta("M", 12))
    assert state.markets["M"].book.yes_bids[Decimal("42.01")] == Decimal("1.50")
    assert state.apply(delta("M", 12)) is None
    assert state.markets["M"].book.yes_bids[Decimal("42.01")] == Decimal("1.50")
    with pytest.raises(StreamInvalid):
        state.apply(delta("N", 14))
    assert not state.connected
    assert all(m.book is None for m in state.markets.values())


@pytest.mark.parametrize(
    "message",
    [
        delta(),
        {
            **snapshot(),
            "msg": {
                "market_ticker": "M",
                "yes_dollars_fp": [["0.70", "1"]],
                "no_dollars_fp": [["0.40", "1"]],
            },
        },
        {"type": "error", "msg": {"code": 7}},
        {"type": "unsubscribed", "sid": 1},
        {"type": "orderbook_delta", "sid": 999, "seq": 1, "msg": {}},
    ],
)
def test_invalid_messages_fail_closed(message):
    state = connected()
    with pytest.raises((StreamInvalid, ValueError)):
        state.apply(message)
    assert not state.connected
    assert not state.account_reconciled


def test_negative_depth_and_bad_decimal_invalidate_stream():
    state = connected()
    ready(state)
    with pytest.raises(StreamInvalid):
        state.apply(delta(quantity="-1.26"))
    assert not state.connected
    state = connected()
    ready(state)
    with pytest.raises(ValueError):
        state.apply(delta(quantity="NaN"))
    assert not state.connected


def test_staleness_and_close_time_gate_without_messages():
    state = connected()
    ready(state)
    state.clock = lambda: 131
    assert state.trading_block_reason("M") == "stale market book"
    state.clock = lambda: 100
    state.wall_clock = lambda: 2000
    assert state.trading_block_reason("M") == "market closed"


def test_lifecycle_deactivation_and_grid_change():
    state = connected()
    ready(state)
    emit(
        state,
        "market_lifecycle_v2",
        "market_lifecycle_v2",
        {
            "market_ticker": "M",
            "event_type": "deactivated",
        },
        1,
    )
    assert state.trading_block_reason("M")
    state.apply(snapshot(seq=2))
    assert state.trading_block_reason("M") == "market is not active"
    emit(
        state,
        "market_lifecycle_v2",
        "market_lifecycle_v2",
        {
            "market_ticker": "M",
            "event_type": "activated",
        },
        2,
    )
    assert state.trading_block_reason("M")
    state.apply(snapshot(seq=3))
    state.require_trading_ready("M")
    emit(
        state,
        "market_lifecycle_v2",
        "market_lifecycle_v2",
        {
            "market_ticker": "M",
            "event_type": "price_level_structure_updated",
            "price_level_structure": "new_structure",
        },
        3,
    )
    state.apply(snapshot(seq=4))
    assert not state.account_reconciled
    assert "price_ranges" not in state.markets["M"].metadata


def test_private_updates_decimals_dedup_and_group_latch():
    state = connected()
    ready(state)
    token = state.reconciliation_token
    emit(
        state,
        "user_orders",
        "user_order",
        {
            "order_id": "O",
            "ticker": "M",
            "status": "resting",
            "remaining_count_fp": "1.25",
            "yes_price_dollars": "0.4201",
            "subaccount_number": 3,
        },
    )
    emit(state, "user_orders", "user_order", {"order_id": "O", "status": "canceled"})
    assert state.orders["O"]["remaining_count_fp"] == Decimal("1.25")
    assert state.orders["O"]["status"] == "canceled"
    fill = {"trade_id": "T", "order_id": "O", "market_ticker": "M", "count_fp": "0.25"}
    emit(state, "fill", "fill", fill)
    assert emit(state, "fill", "fill", fill) is None
    assert len(state.fills) == 1
    assert not state.positions
    emit(
        state,
        "market_positions",
        "market_position",
        {
            "market_ticker": "M",
            "subaccount": 3,
            "position_fp": "-0.25",
            "position_cost_dollars": "0.105025",
        },
    )
    assert state.positions[(3, "M")]["position_fp"] == Decimal("-0.25")
    with pytest.raises(TradingHalted):
        state.confirm_reconciled(token)
    for seq, event in enumerate(
        ["created", "triggered", "limit_updated", "reset", "deleted"], 1
    ):
        emit(
            state,
            "order_group_updates",
            "order_group_updates",
            {
                "order_group_id": "G",
                "event_type": event,
                "contracts_limit_fp": "1.50",
            },
            seq,
        )
        assert bool(state.trading_block_reason("M", "G")) == (
            event in {"triggered", "limit_updated", "deleted"}
        )
    assert state.order_groups["G"]["contracts_limit_fp"] == Decimal("1.50")


def test_reconciliation_token_rejects_previous_connection():
    state = connected()
    token = state.reconciliation_token
    state.connect()
    with pytest.raises(TradingHalted):
        state.confirm_reconciled(token)


def test_unknown_group_one_sided_and_off_grid_are_blocked():
    state = connected()
    ready(state)
    assert state.trading_block_reason("M", "UNKNOWN")
    state.markets["M"].book.no_bids.clear()
    assert state.trading_block_reason("M") == "two-sided book required"
    state.apply(snapshot(seq=2))
    state.markets["M"].metadata["price_ranges"][0]["step"] = Decimal("0.01")
    assert state.trading_block_reason("M") == "book contains off-grid price"


@pytest.mark.parametrize("close", ["bad-date", float("nan"), float("inf"), {}])
def test_bad_close_metadata_blocks_trading(close):
    state = connected()
    ready(state)
    state.markets["M"].metadata["close_ts"] = close
    assert state.trading_block_reason("M") == "invalid market close time"


def test_locked_book_and_zero_depth_are_blocked():
    state = connected()
    ready(state)
    book = state.markets["M"].book
    book.no_bids = {Decimal("57.99"): Decimal("1")}
    assert state.trading_block_reason("M") == "locked market book"
    book.no_bids = {Decimal("57.01"): Decimal("0")}
    assert state.trading_block_reason("M") == "nonpositive top-of-book depth"

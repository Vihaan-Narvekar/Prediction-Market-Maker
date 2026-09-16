import asyncio
from unittest.mock import AsyncMock, Mock

import orjson
import pytest
from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Close

from eventmm.kalshi.stream_state import DEFAULT_CHANNELS, StreamInvalid, TradingHalted
from eventmm.kalshi.ws_client import KalshiWebSocketClient


def client(handler=None, **kwargs):
    return KalshiWebSocketClient(
        "wss://example.test/trade-api/ws/v2",
        Mock(),
        ["M"],
        handler or AsyncMock(),
        **kwargs,
    )


async def acknowledge(ws):
    ws.state.connect()
    commands = ws._subscriptions()
    for sid, command in enumerate(commands, 1):
        await ws.handle_message(
            {
                "id": command["id"],
                "type": "subscribed",
                "msg": {
                    "channel": command["params"]["channels"][0],
                    "sid": sid,
                },
            }
        )


def test_subscriptions_use_actual_channel_names_and_correct_scope():
    ws = client()
    commands = ws._subscriptions()
    assert len({command["id"] for command in commands}) == len(DEFAULT_CHANNELS)
    for command in commands:
        params = command["params"]
        if params["channels"] == ["orderbook_delta"]:
            assert params["market_tickers"] == ["M"]
        else:
            assert "market_tickers" not in params
    assert {c["params"]["channels"][0] for c in commands} == set(DEFAULT_CHANNELS)
    assert ws._subscriptions()[0]["id"] > commands[-1]["id"]


@pytest.mark.asyncio
async def test_state_updates_before_handler_and_guard_prevents_submit():
    ws = client()
    await acknowledge(ws)
    submit = AsyncMock()
    with pytest.raises(TradingHalted):
        await ws.execute_when_ready("M", submit)
    submit.assert_not_awaited()

    async def handler(message):
        assert ws.state.orders["O"]["status"] == "resting"

    ws.handler = handler
    sid = next(s for s, c in ws.state.subscriptions.items() if c == "user_orders")
    await ws.handle_message(
        {
            "type": "user_order",
            "sid": sid,
            "msg": {
                "order_id": "O",
                "status": "resting",
                "remaining_count_fp": "1.25",
            },
        }
    )


@pytest.mark.asyncio
async def test_unmatched_ack_and_handler_failure_invalidate():
    ws = client()
    ws.state.connect()
    ws._subscriptions()
    with pytest.raises(StreamInvalid):
        await ws.handle_message(
            {
                "id": 999,
                "type": "subscribed",
                "msg": {
                    "channel": "fill",
                    "sid": 1,
                },
            }
        )
    assert not ws.state.connected
    await acknowledge(ws)
    ws.handler = AsyncMock(side_effect=RuntimeError("consumer failed"))
    with pytest.raises(RuntimeError):
        await ws.handle_message({"type": "ok", "id": 5, "msg": {}})
    assert not ws.state.connected


class Socket:
    def __init__(self):
        self.messages = []
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, raw):
        command = orjson.loads(raw)
        self.sent.append(command)
        if command["cmd"] == "subscribe":
            self.messages.append(
                {
                    "id": command["id"],
                    "type": "subscribed",
                    "msg": {
                        "channel": command["params"]["channels"][0],
                        "sid": len(self.sent),
                    },
                }
            )

    async def recv(self):
        if self.messages:
            return orjson.dumps(self.messages.pop(0))
        raise ConnectionClosedOK(Close(1000, "done"), Close(1000, "done"), True)


@pytest.mark.asyncio
async def test_clean_close_backs_off_resubscribes_and_cancellation_halts(monkeypatch):
    ws = client(reconnect_delay=0.5)
    sockets = [Socket(), Socket()]
    connect = Mock(side_effect=sockets)
    monkeypatch.setattr("eventmm.kalshi.ws_client.websockets.connect", connect)
    sleeps = []

    async def sleep(delay):
        assert not ws.state.connected
        assert not ws.state.account_reconciled
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("eventmm.kalshi.ws_client.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await ws.listen_forever()
    assert sleeps == [0.5, 0.5]
    assert all(len(socket.sent) == len(DEFAULT_CHANNELS) for socket in sockets)
    assert sockets[1].sent[0]["id"] > sockets[0].sent[-1]["id"]
    assert ws.auth.sign_headers.call_count == 2
    assert not ws.state.connected
    assert not ws._running


@pytest.mark.asyncio
async def test_missing_ack_times_out_and_invalidates(monkeypatch):
    ws = client(subscription_timeout=0.01)
    socket = Socket()
    socket.send = AsyncMock()

    async def stalled_recv():
        await asyncio.Future()

    socket.recv = stalled_recv
    monkeypatch.setattr(
        "eventmm.kalshi.ws_client.websockets.connect", Mock(return_value=socket)
    )

    async def sleep(delay):
        assert not ws.state.connected
        raise asyncio.CancelledError

    monkeypatch.setattr("eventmm.kalshi.ws_client.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await ws.listen_forever()
    assert not ws._pending


@pytest.mark.asyncio
async def test_guard_allows_ready_submit_but_stops_after_disconnect():
    ws = client()
    await acknowledge(ws)
    ws.state.clock = lambda: 10
    ws.state.wall_clock = lambda: 10
    ws.state.apply(
        {
            "type": "orderbook_snapshot",
            "sid": 1,
            "seq": 1,
            "msg": {
                "market_ticker": "M",
                "yes_dollars_fp": [["0.4", "1"]],
                "no_dollars_fp": [["0.5", "1"]],
            },
        }
    )
    ws.state.set_market_metadata(
        "M",
        {
            "status": "active",
            "close_ts": 100,
            "price_ranges": [{"start": "0", "end": "1", "step": "0.01"}],
        },
        ws.state.reconciliation_token,
    )
    ws.state.reconcile_account(
        orders=[], positions=[], order_groups=[], token=ws.state.reconciliation_token
    )
    submit = AsyncMock(return_value={"order_id": "new"})
    assert await ws.execute_when_ready("M", submit) == {"order_id": "new"}
    ws.state.disconnect()
    with pytest.raises(TradingHalted):
        await ws.execute_when_ready("M", submit)
    assert submit.await_count == 1

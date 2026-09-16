import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from eventmm.collector.archive import Archive, ArchiveError
from eventmm.collector.service import CollectorConfig, MarketCollector
from eventmm.collector.supervisor import health, terminate
from eventmm.kalshi.rate_limiter import TokenBucket
from eventmm.kalshi.rest_client import KalshiRestClient
from eventmm.kalshi.ws_client import KalshiWebSocketClient


def test_archive_restart_retains_exact_frames_and_checkpoints(tmp_path):
    path = tmp_path / "raw.sqlite3"
    archive = Archive(path)
    raw = b'{ "type":"trade", "count_fp":"1.2500" }'
    record = archive.append("websocket", raw, "session1")
    archive.checkpoint("cursor", {"ts": 123})
    archive.trade({"trade_id": "t", "count_fp": Decimal("1.25")})
    archive.trade({"trade_id": "t", "count_fp": "1.25"})
    with pytest.raises(BlockingIOError):
        Archive(path)
    archive.close()
    reopened = Archive(path)
    assert (
        reopened.db.execute(
            "SELECT payload FROM records WHERE id=?", (record,)
        ).fetchone()[0]
        == raw
    )
    assert reopened.get_checkpoint("cursor") == {"ts": 123}
    assert reopened.db.execute("SELECT count(*) FROM trades").fetchone()[0] == 1
    assert reopened.db.execute("PRAGMA synchronous").fetchone()[0] == 2
    reopened.close()


def test_archive_failure_is_fatal(tmp_path):
    archive = Archive(tmp_path / "raw.sqlite3")
    archive.db.execute("PRAGMA query_only=ON")
    with pytest.raises(ArchiveError):
        archive.append("websocket", b"lost")
    archive.close()


@pytest.mark.asyncio
async def test_http_retries_rate_limit_each_attempt_and_archives_responses(monkeypatch):
    seen = []
    sleeps = []

    async def handler(request):
        seen.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "3"})
            if len(seen) == 1
            else httpx.Response(200, json={"trades": []})
        )

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("eventmm.kalshi.http_budget.asyncio.sleep", sleep)
    limiter = Mock(acquire=AsyncMock())
    hook = AsyncMock()
    client = KalshiRestClient("https://test", rate_limiter=limiter, response_hook=hook)
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await client.get_trades("M", cursor="p2", min_ts=1, max_ts=2)
        assert limiter.acquire.await_count == 2
        assert hook.await_count == 2
        assert sleeps == [3]
        assert seen[-1].url.params["cursor"] == "p2"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_no_retry_auth_errors_and_finite_retry_deadline():
    client = KalshiRestClient("https://test", retry_budget=0.02)
    await client.client.aclose()
    handler = Mock(return_value=httpx.Response(401))
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_trades("M")
    assert handler.call_count == 1
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "1000"})
        )
    )
    with pytest.raises(TimeoutError):
        await client.get_trades("M")
    await client.close()


@pytest.mark.asyncio
async def test_pagination_exhaustion_and_loop_are_explicit():
    client = KalshiRestClient("https://test")
    fetch = AsyncMock(side_effect=[{"markets": [1], "cursor": "x"}, {"markets": [2]}])
    assert [p async for p in client.pages(fetch)] == [
        {"markets": [1], "cursor": "x"},
        {"markets": [2]},
    ]
    assert fetch.call_args_list[1].kwargs["cursor"] == "x"
    with pytest.raises(RuntimeError, match="repeated"):
        _ = [p async for p in client.pages(AsyncMock(return_value={"cursor": "x"}))]
    with pytest.raises(RuntimeError, match="budget"):
        _ = [
            p
            async for p in client.pages(
                AsyncMock(return_value={"cursor": "x"}), max_pages=1
            )
        ]
    await client.close()


@pytest.mark.parametrize("capacity,rate", [(0, 1), (1, 0), (float("nan"), 1)])
def test_invalid_rate_budgets(capacity, rate):
    with pytest.raises(ValueError):
        TokenBucket(capacity, rate)


@pytest.mark.asyncio
async def test_impossible_token_cost_fails():
    with pytest.raises(ValueError):
        await TokenBucket(1, 1).acquire(2)


class IdleWS:
    def __init__(self, url, auth, tickers, handler, **kwargs):
        self.market_tickers = tickers
        self.cancelled = False

    async def listen_forever(self):
        try:
            await asyncio.Future()
        finally:
            self.cancelled = True


@pytest.fixture
def collector(tmp_path):
    archive = Archive(tmp_path / "raw.sqlite3")
    rest = KalshiRestClient("https://test")
    service = MarketCollector(
        rest,
        Mock(),
        "wss://test",
        archive,
        CollectorConfig(("SERIES",)),
        ws_factory=IdleWS,
    )
    yield service
    archive.close()


@pytest.mark.asyncio
async def test_dynamic_enrollment_and_failed_discovery_preserves_universe(collector):
    collector.rest.get_markets = AsyncMock(
        side_effect=[
            {"markets": [{"ticker": "M"}], "cursor": "next"},
            {"markets": [{"ticker": "N"}]},
            {"markets": [{"ticker": "N"}]},
            RuntimeError("API down"),
            {"markets": []},
        ]
    )
    try:
        await collector.discover()
        await asyncio.sleep(0)
        first = collector.ws
        assert first.market_tickers == ["M", "N"]
        await collector.discover()
        await asyncio.sleep(0)
        assert first.cancelled
        assert collector.ws.market_tickers == ["N"]
        with pytest.raises(RuntimeError):
            await collector.discover()
        assert set(collector.markets) == {"N"}
        assert collector.known == {"M", "N"}
        await collector.discover()
        assert collector.ws is None
    finally:
        await collector.stop_listener()
        await collector.rest.close()


@pytest.mark.asyncio
async def test_trade_checkpoint_only_advances_after_complete_window(collector):
    collector.archive.checkpoint("trades:M", 200)
    collector.rest.get_historical_cutoff = AsyncMock(
        return_value={"trades_created_ts": "1970-01-01T00:05:00Z"}
    )
    collector.rest.get_historical_trades = AsyncMock(
        return_value={"trades": [{"trade_id": "old"}]}
    )
    collector.rest.get_trades = AsyncMock(
        side_effect=[
            {"trades": [{"trade_id": "new"}], "cursor": "x"},
            RuntimeError("page failed"),
        ]
    )
    try:
        with pytest.raises(RuntimeError):
            await collector.backfill("M")
        assert collector.archive.get_checkpoint("trades:M") == 200
        collector.rest.get_trades = AsyncMock(
            return_value={"trades": [{"trade_id": "new"}]}
        )
        await collector.backfill("M")
        assert collector.archive.get_checkpoint("trades:M") > 200
        assert (
            collector.archive.db.execute("SELECT count(*) FROM trades").fetchone()[0]
            == 2
        )
        assert collector.rest.get_historical_trades.call_args.kwargs["max_ts"] == 300
        assert collector.rest.get_trades.call_args.kwargs["min_ts"] == 300
    finally:
        await collector.rest.close()


@pytest.mark.asyncio
async def test_raw_trade_archive_and_decimal_state(tmp_path):
    archive = Archive(tmp_path / "raw.sqlite3")
    handler = AsyncMock()
    ws = KalshiWebSocketClient(
        "wss://test", Mock(), ["M"], handler, channels=("trade",)
    )
    command = ws._subscriptions()[0]
    assert command["params"]["market_tickers"] == ["M"]
    ws.state.connect()
    await ws.handle_message(
        {
            "type": "subscribed",
            "id": command["id"],
            "msg": {"sid": 1, "channel": "trade"},
        }
    )
    await ws.handle_message(
        {
            "type": "trade",
            "sid": 1,
            "seq": 1,
            "msg": {
                "trade_id": "T",
                "market_ticker": "M",
                "yes_price_dollars": "0.1234",
                "count_fp": "1.25",
            },
        }
    )
    assert handler.call_args.args[0]["msg"]["count_fp"] == Decimal("1.25")
    archive.close()


def test_health_detects_disconnection_and_stale_discovery(tmp_path):
    path = tmp_path / "raw.sqlite3"
    archive = Archive(path)
    state = {
        "heartbeat": time.time(),
        "last_discovery": time.time(),
        "last_frame": time.time(),
        "connected": True,
        "markets": 1,
    }
    archive.checkpoint("health", state)
    assert health(path, 60)["connected"]
    archive.checkpoint("health", {**state, "connected": False})
    with pytest.raises(RuntimeError, match="disconnected"):
        health(path, 60)
    archive.checkpoint("health", {**state, "last_discovery": 1})
    with pytest.raises(RuntimeError, match="discovery"):
        health(path, 60)
    archive.close()


@pytest.mark.asyncio
async def test_supervisor_terminates_and_reaps_child():
    process = Mock(returncode=None, wait=AsyncMock())
    await terminate(process)
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_frame_archived_before_reconnect_and_storage_failure_stops(
    monkeypatch,
):
    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            pass

        async def recv(self):
            return b"{malformed"

    raw = AsyncMock()
    ws = KalshiWebSocketClient(
        "wss://test", Mock(), ["M"], AsyncMock(), raw_handler=raw
    )
    monkeypatch.setattr(
        "eventmm.kalshi.ws_client.websockets.connect", Mock(return_value=Socket())
    )

    async def stop(delay):
        raise asyncio.CancelledError

    monkeypatch.setattr("eventmm.kalshi.ws_client.asyncio.sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await ws.listen_forever()
    assert raw.call_args.args[0] == b"{malformed"
    assert not ws.state.connected
    raw.side_effect = ArchiveError("disk full")
    with pytest.raises(ArchiveError):
        await ws.listen_forever()
    assert not ws.state.connected


@pytest.mark.asyncio
async def test_noaa_pagination_follows_reported_count():
    from eventmm.external.noaa_client import NOAAClient

    requests = []

    async def handler(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        return httpx.Response(
            200,
            json={
                "metadata": {"resultset": {"count": 3}},
                "results": [{"value": offset}, {"value": offset + 1}]
                if offset == 1
                else [{"value": 3}],
            },
        )

    client = NOAAClient("not-a-real-token", transport=httpx.MockTransport(handler))
    client.rate_limiter = Mock(acquire=AsyncMock())
    try:
        page = await client.get_daily_data(
            "GHCND", "GHCND:STATION", "2026-01-01", "2026-01-03", ["TMAX"]
        )
        assert len(page["results"]) == 3
        assert requests[1].url.params["offset"] == "3"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stale_market_recovery_timeout_even_with_other_traffic(collector):
    from eventmm.kalshi.stream_state import StreamState

    ws = Mock(
        state=StreamState(["M", "N"]), request_snapshots=AsyncMock(return_value=True)
    )
    ws.state.connect()
    collector.ws = ws
    try:
        await collector.monitor()
        ws.request_snapshots.assert_awaited_once_with(["M", "N"])
        collector.refresh_requested["M"] = time.monotonic() - 1000
        with pytest.raises(RuntimeError, match="Snapshot recovery"):
            await collector.monitor()
    finally:
        await collector.rest.close()


@pytest.mark.asyncio
async def test_supervisor_restarts_failed_child_and_cancellation_reaps(
    monkeypatch, tmp_path
):
    from eventmm.collector.supervisor import supervise_worker

    process = Mock(returncode=1, wait=AsyncMock(return_value=1), pid=42)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(
        "eventmm.collector.supervisor.asyncio.create_subprocess_exec", spawn
    )
    delays = []

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("eventmm.collector.supervisor.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await supervise_worker("worker", ["example"], tmp_path / "archive", 60)
    assert spawn.await_count == 2
    assert delays == [2, 4]


@pytest.mark.asyncio
async def test_service_ingests_reconciles_enrolls_and_shuts_down(monkeypatch, tmp_path):
    """Whole service with real parsers/archive and fake exchange transports."""
    import orjson

    class ExchangeSocket:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.sid = 0
            self.book_seq = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            command = orjson.loads(raw)
            params = command["params"]
            if command["cmd"] == "subscribe":
                self.sid += 1
                channel = params["channels"][0]
                await self.queue.put(
                    {
                        "id": command["id"],
                        "type": "subscribed",
                        "msg": {"sid": self.sid, "channel": channel},
                    }
                )
                if channel == "trade":
                    await self.queue.put(
                        {
                            "type": "trade",
                            "sid": self.sid,
                            "seq": 1,
                            "msg": {
                                "trade_id": "T",
                                "market_ticker": "M",
                                "count_fp": "0.25",
                                "yes_price_dollars": "0.4001",
                            },
                        }
                    )
                if channel != "orderbook_delta":
                    return
            for ticker in params.get("market_tickers", []):
                self.book_seq += 1
                await self.queue.put(
                    {
                        "type": "orderbook_snapshot",
                        "sid": 1,
                        "seq": self.book_seq,
                        "msg": {
                            "market_ticker": ticker,
                            "yes_dollars_fp": [["0.4001", "0.25"]],
                            "no_dollars_fp": [["0.5", "1"]],
                        },
                    }
                )

        async def recv(self):
            return orjson.dumps(await self.queue.get())

    monkeypatch.setattr(
        "eventmm.kalshi.ws_client.websockets.connect", lambda *a, **kw: ExchangeSocket()
    )
    discoveries = 0

    async def http(request):
        nonlocal discoveries
        if request.url.path == "/markets":
            discoveries += 1
            return httpx.Response(
                200,
                json={
                    "markets": [
                        {"ticker": t}
                        for t in (["M"] if discoveries == 1 else ["M", "N"])
                    ]
                },
            )
        if request.url.path.endswith("cutoff"):
            return httpx.Response(
                200, json={"trades_created_ts": "2020-01-01T00:00:00Z"}
            )
        if request.url.path.endswith("trades"):
            return httpx.Response(
                200, json={"trades": [{"trade_id": "T", "count_fp": "0.25"}]}
            )
        return httpx.Response(
            200,
            json={
                "orderbook_fp": {
                    "yes_dollars": [["0.4001", "0.25"]],
                    "no_dollars": [["0.5", "1"]],
                }
            },
        )

    archive = Archive(tmp_path / "raw.sqlite3")
    rest = KalshiRestClient("https://test", rate_limiter=Mock(acquire=AsyncMock()))
    await rest.client.aclose()
    rest.client = httpx.AsyncClient(transport=httpx.MockTransport(http))
    service = MarketCollector(
        rest,
        Mock(),
        "wss://test",
        archive,
        CollectorConfig(("S",), discovery_seconds=0.05, reconcile_seconds=0.05),
    )
    task = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            while not (
                service.ws
                and "N" in service.ws.state.markets
                and all(m.book for m in service.ws.state.markets.values())
                and service.last_reconcile
            ):
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        assert not service.ws.state.account_reconciled
        assert archive.db.execute("SELECT count(*) FROM trades").fetchone()[0] == 1
        assert (
            archive.db.execute(
                "SELECT count(DISTINCT session) FROM records WHERE kind='websocket'"
            ).fetchone()[0]
            == 2
        )
        assert (
            archive.db.execute(
                "SELECT count(*) FROM records WHERE kind='rest'"
            ).fetchone()[0]
            > 0
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.ws is None
        assert rest.client.is_closed
        archive.close()

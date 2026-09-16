"""Read-only ingestion with independent discovery, backfill, and health loops."""

import asyncio
import time
from dataclasses import dataclass

import structlog

from eventmm.collector.archive import Archive, ArchiveError
from eventmm.kalshi.stream_state import DEFAULT_CHANNELS
from eventmm.kalshi.ws_client import KalshiWebSocketClient
from eventmm.lob.parsing import parse_rest_orderbook

logger = structlog.get_logger()
PUBLIC_CHANNELS = ("orderbook_delta", "trade", "market_lifecycle_v2")


@dataclass(frozen=True)
class CollectorConfig:
    series: tuple[str, ...]
    discovery_seconds: float = 60
    reconcile_seconds: float = 120
    stale_seconds: float = 60
    backfill_seconds: int = 3600
    max_markets: int = 1000
    private: bool = False
    retirement_seconds: float = 86400

    def __post_init__(self):
        if not self.series or any(not s for s in self.series):
            raise ValueError("At least one explicit series is required")
        if (
            min(
                self.discovery_seconds,
                self.reconcile_seconds,
                self.stale_seconds,
                self.backfill_seconds,
                self.max_markets,
                self.retirement_seconds,
            )
            <= 0
        ):
            raise ValueError("Collector limits must be positive")


class MarketCollector:
    def __init__(
        self,
        rest,
        auth,
        ws_url: str,
        archive: Archive,
        config: CollectorConfig,
        ws_factory=KalshiWebSocketClient,
    ):
        self.rest, self.auth, self.ws_url = rest, auth, ws_url
        self.archive, self.config, self.ws_factory = archive, config, ws_factory
        self.markets: dict[str, dict] = {}
        self.known = set(archive.get_checkpoint("known_markets", []))
        self.retired: dict[str, float] = archive.get_checkpoint("retired_markets", {})
        self.ws: KalshiWebSocketClient | None = None
        self.listener: asyncio.Task | None = None
        self.refresh_requested: dict[str, float] = {}
        self.last_discovery: float | None = None
        self.last_reconcile: float | None = None
        self.last_frame: float | None = None
        self.started_at = time.time()
        self.rest.response_hook = self.archive_response

    async def archive_response(self, response):
        self.archive.append(
            "rest",
            {
                "url": str(response.request.url),
                "status": response.status_code,
                "body": response.text,
            },
        )

    async def raw(self, frame, session):
        # Synchronous FULL commits deliberately backpressure the bounded WS queue.
        # Persistence failure escapes the reconnect loop and stops the process.
        self.archive.append("websocket", frame, session)
        self.last_frame = time.time()

    async def session(self, event, session):
        self.archive.append(
            "session", {"event": event, "tickers": sorted(self.markets)}, session
        )
        self.refresh_requested.clear()

    async def message(self, message):
        if message["type"] == "trade":
            self.archive.trade(message["msg"])
        elif message["type"] == "orderbook_snapshot":
            self.refresh_requested.pop(message["msg"]["market_ticker"], None)

    async def discover(self):
        found: dict[str, dict] = {}
        for series in self.config.series:
            async for page in self.rest.pages(
                self.rest.get_markets, status="open", series_ticker=series
            ):
                for market in page["markets"]:
                    found[market["ticker"]] = market
                    if len(found) > self.config.max_markets:
                        raise RuntimeError(
                            "Market cap exceeded; increase cap or narrow series"
                        )
        changed = set(found) != set(self.markets)
        self.archive.append("universe", {"markets": found, "changed": changed})
        for ticker in found:
            if self.archive.get_checkpoint("trades:" + ticker) is None:
                self.archive.checkpoint(
                    "trades:" + ticker, int(time.time()) - self.config.backfill_seconds
                )
        for ticker in found:
            self.retired.pop(ticker, None)
        for ticker in self.known - set(found):
            self.retired.setdefault(ticker, time.time())
        self.archive.checkpoint("retired_markets", self.retired)
        self.known.update(found)
        self.archive.checkpoint("known_markets", sorted(self.known))
        if changed:
            # A full new epoch is explicit and safe: no deltas bridge enrollment.
            await self.stop_listener()
            self.markets = found
            if found:
                channels = (
                    tuple(dict.fromkeys((*DEFAULT_CHANNELS, "trade")))
                    if self.config.private
                    else PUBLIC_CHANNELS
                )
                self.ws = self.ws_factory(
                    self.ws_url,
                    self.auth,
                    sorted(found),
                    self.message,
                    channels=channels,
                    stale_after=self.config.stale_seconds,
                    raw_handler=self.raw,
                    session_handler=self.session,
                    reconnect_max_delay=60,
                )
                self.listener = asyncio.create_task(self.ws.listen_forever())
        else:
            self.markets = found
        self.last_discovery = time.time()

    async def stop_listener(self):
        listener, self.listener = self.listener, None
        self.ws = None
        if listener:
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise

    async def backfill(self, ticker):
        end = int(time.time())
        start = max(
            0,
            int(
                self.archive.get_checkpoint(
                    "trades:" + ticker, end - self.config.backfill_seconds
                )
            )
            - 60,
        )
        # Query a fixed time window; advance only after every page commits.
        # Recent live collection uses /markets/trades. Older history is split at
        # the exchange's advertised cutoff instead of silently losing old rows.
        cutoff_data = await self.rest.get_historical_cutoff()
        cutoff_value = cutoff_data.get("trades_created_ts")
        if cutoff_value is not None:
            from datetime import datetime

            cutoff = int(
                datetime.fromisoformat(cutoff_value.replace("Z", "+00:00")).timestamp()
            )
        else:
            raise ValueError("Missing historical trade cutoff")
        ranges = []
        if start <= cutoff:
            ranges.append((self.rest.get_historical_trades, start, min(end, cutoff)))
        if end >= cutoff:
            ranges.append((self.rest.get_trades, max(start, cutoff), end))
        for fetch, lower, upper in ranges:
            async for page in self.rest.pages(
                fetch, ticker=ticker, min_ts=lower, max_ts=upper
            ):
                for trade in page["trades"]:
                    self.archive.trade(trade)
        self.archive.checkpoint("trades:" + ticker, end)

    async def reconcile(self):
        failed = False
        for ticker in sorted(self.known):
            try:
                await self.backfill(ticker)
                ws = self.ws
                if ticker in self.markets:
                    before = (ws.state.epoch, dict(ws.state.sequences)) if ws else None
                    payload = await self.rest.get_orderbook(ticker)
                    rest_yes, rest_no = parse_rest_orderbook(payload)
                    market = ws.state.markets.get(ticker) if ws else None
                    if not ws or ws is not self.ws or not market or not market.book:
                        result = "no_live_baseline"
                    elif before != (ws.state.epoch, ws.state.sequences):
                        result = "concurrent_updates"
                    else:
                        result = (
                            "match"
                            if (
                                market.book.yes_bids == rest_yes
                                and market.book.no_bids == rest_no
                            )
                            else "mismatch"
                        )
                    self.archive.append(
                        "reconciliation", {"ticker": ticker, "result": result}
                    )
                    if result == "mismatch" and ws and market:
                        market.book = None
                        market.invalid_reason = (
                            "REST mismatch; awaiting sequenced snapshot"
                        )
                        await ws.request_snapshots([ticker])
                else:
                    # Retain a catch-up window for late-indexed trades and settlement.
                    metadata = await self.rest.get_market(ticker)
                    self.archive.append("retired_metadata", metadata)
                    if (
                        time.time() - self.retired.get(ticker, time.time())
                        >= self.config.retirement_seconds
                    ):
                        self.known.discard(ticker)
                        self.retired.pop(ticker, None)
                        self.archive.checkpoint("known_markets", sorted(self.known))
                        self.archive.checkpoint("retired_markets", self.retired)
            except ArchiveError:
                raise
            except Exception as exc:
                failed = True
                self.archive.append(
                    "error",
                    {"operation": "reconcile", "ticker": ticker, "error": str(exc)},
                )
                logger.warning("reconciliation_failed", ticker=ticker, error=str(exc))
        if not failed:
            self.last_reconcile = time.time()

    async def monitor(self):
        if self.listener and self.listener.done():
            await self.listener  # propagate fatal persistence / programming errors
            raise RuntimeError("WebSocket listener stopped unexpectedly")
        ws = self.ws
        if ws and ws.state.connected:
            now = time.monotonic()
            stale = []
            for ticker, market in ws.state.markets.items():
                requested = self.refresh_requested.get(ticker)
                if (
                    requested is not None
                    and now - requested > self.config.stale_seconds
                ):
                    # Missing per-market snapshots can hide behind other active books.
                    raise RuntimeError(f"Snapshot recovery timed out: {ticker}")
                if requested is None and (
                    market.received_at is None
                    or now - market.received_at > self.config.stale_seconds / 2
                ):
                    stale.append(ticker)
            if stale and await ws.request_snapshots(stale):
                self.refresh_requested.update(dict.fromkeys(stale, now))
        self.archive.checkpoint(
            "health",
            {
                "heartbeat": time.time(),
                "started_at": self.started_at,
                "reconcile_max_age": max(1800, self.config.reconcile_seconds * 3),
                "last_discovery": self.last_discovery,
                "last_reconcile": self.last_reconcile,
                "last_frame": self.last_frame,
                "markets": len(self.markets),
                "connected": bool(ws and ws.state.connected),
                "trading_enabled": False,
                "valid_books": sum(
                    m.book is not None and not m.invalid_reason
                    for m in ws.state.markets.values()
                )
                if ws
                else 0,
            },
        )

    async def periodic(self, operation, interval, *, fatal=False):
        while True:
            try:
                await operation()
            except ArchiveError:
                raise
            except Exception as exc:
                if fatal:
                    raise
                self.archive.append(
                    "error", {"operation": operation.__name__, "error": str(exc)}
                )
                logger.warning(
                    "collector_operation_failed",
                    operation=operation.__name__,
                    error=str(exc),
                )
            await asyncio.sleep(interval)

    async def run(self):
        self.archive.append("collector_started", {"series": self.config.series})
        try:
            await self.discover()
            async with asyncio.TaskGroup() as group:
                group.create_task(
                    self.periodic(self.discover, self.config.discovery_seconds)
                )
                group.create_task(
                    self.periodic(self.reconcile, self.config.reconcile_seconds)
                )
                group.create_task(self.periodic(self.monitor, 5, fatal=True))
        finally:
            try:
                await self.stop_listener()
            finally:
                await self.rest.close()

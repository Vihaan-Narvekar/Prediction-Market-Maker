import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import orjson
import structlog
import websockets

from eventmm.kalshi.auth import KalshiAuth
from eventmm.collector.archive import ArchiveError
from eventmm.kalshi.stream_state import (
    DEFAULT_CHANNELS,
    SUPPORTED_CHANNELS,
    StreamInvalid,
    StreamState,
)

logger = structlog.get_logger()
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
T = TypeVar("T")


class KalshiWebSocketClient:
    def __init__(
        self,
        ws_url: str,
        auth: KalshiAuth,
        market_tickers: list[str],
        handler: MessageHandler,
        reconnect_delay: float = 2.0,
        *,
        channels: tuple[str, ...] = DEFAULT_CHANNELS,
        stale_after: float = 30.0,
        subscription_timeout: float = 10.0,
        raw_handler=None,
        session_handler=None,
        reconnect_max_delay: float | None = None,
    ):
        if (
            not market_tickers
            or not channels
            or not set(channels) <= set(SUPPORTED_CHANNELS)
        ):
            raise ValueError("Market tickers and supported channels are required")
        if reconnect_delay < 0 or subscription_timeout <= 0:
            raise ValueError("Invalid reconnect delay or subscription timeout")
        if reconnect_max_delay is not None and reconnect_max_delay < reconnect_delay:
            raise ValueError("Maximum reconnect delay must be at least initial delay")
        self.reconnect_max_delay = reconnect_max_delay or reconnect_delay
        self.raw_handler = raw_handler
        self.session_handler = session_handler
        self.session_id = ""
        self._websocket: Any = None
        self.ws_url = ws_url
        self.auth = auth
        self.market_tickers = list(dict.fromkeys(market_tickers))
        self.handler = handler
        self.reconnect_delay = reconnect_delay
        self.channels = tuple(dict.fromkeys(channels))
        self.subscription_timeout = subscription_timeout
        self.state = StreamState(self.market_tickers, stale_after=stale_after)
        self._next_id = 0
        self._pending: dict[int, str] = {}
        self._running = False

    def _command(self, cmd: str, params: dict) -> dict[str, Any]:
        self._next_id += 1
        return {"id": self._next_id, "cmd": cmd, "params": params}

    def _subscriptions(self) -> list[dict[str, Any]]:
        self._pending.clear()
        commands = []
        for channel in self.channels:
            params: dict[str, Any] = {"channels": [channel]}
            if channel in {"orderbook_delta", "trade"}:
                params["market_tickers"] = self.market_tickers
            # Account channels deliberately cover ALL account activity; lifecycle
            # and group channels do not support ticker filtering.
            command = self._command("subscribe", params)
            self._pending[command["id"]] = channel
            commands.append(command)
        return commands

    async def handle_message(self, message: dict[str, Any]) -> None:
        try:
            if message.get("type") == "subscribed":
                channel = message["msg"]["channel"]
                if self._pending.pop(message["id"], None) != channel:
                    raise StreamInvalid("Unmatched subscription acknowledgement")
            normalized = self.state.apply(message)
            if normalized is not None:
                await self.handler(normalized)
        except BaseException:
            self.state.disconnect("message processing failed")
            raise

    async def execute_when_ready(
        self,
        ticker: str,
        submit: Callable[[], Awaitable[T]],
        *,
        order_group_id: str | None = None,
    ) -> T:
        """Gate a new order/amendment immediately before calling its transport.

        The submit adapter must not queue or delay without rechecking the gate.
        Risk-reducing cancellation is intentionally outside this gate.
        """
        self.state.require_trading_ready(ticker, order_group_id)
        return await submit()

    async def request_snapshots(self, tickers: list[str]) -> bool:
        """Refresh through the sequenced WS channel; REST isn't a delta baseline."""
        if self._websocket is None:
            return False
        for sid, channel in self.state.subscriptions.items():
            if channel == "orderbook_delta":
                command = self._command(
                    "update_subscription",
                    {
                        "sid": sid,
                        "action": "get_snapshot",
                        "market_tickers": tickers,
                    },
                )
                await self._websocket.send(orjson.dumps(command).decode())
                return True
        return False

    async def listen_forever(self) -> None:
        if self._running:
            raise RuntimeError("WebSocket listener is already running")
        self._running = True
        backoff = self.reconnect_delay
        try:
            while True:
                try:
                    headers = self.auth.sign_headers("GET", self.ws_url)
                    async with websockets.connect(
                        self.ws_url,
                        additional_headers=headers,
                        ping_interval=10,
                        ping_timeout=10,
                        max_queue=64,
                    ) as websocket:
                        self.session_id = str(uuid.uuid4())
                        self._websocket = websocket
                        connected_at = asyncio.get_running_loop().time()
                        self.state.connect()
                        if self.session_handler:
                            await self.session_handler("connected", self.session_id)
                        logger.info(
                            "ws_connected",
                            markets=self.market_tickers,
                            epoch=self.state.epoch,
                        )
                        for command in self._subscriptions():
                            await websocket.send(orjson.dumps(command).decode())
                        deadline = (
                            asyncio.get_running_loop().time()
                            + self.subscription_timeout
                        )
                        while True:
                            if self._pending:
                                timeout = deadline - asyncio.get_running_loop().time()
                                if timeout <= 0:
                                    raise StreamInvalid(
                                        "Subscription acknowledgement timeout"
                                    )
                            else:
                                timeout = self.state.stale_after
                            async with asyncio.timeout(timeout):
                                raw = await websocket.recv()
                            if self.raw_handler:
                                await self.raw_handler(raw, self.session_id)
                            message = orjson.loads(raw)
                            await self.handle_message(message)
                            if (
                                not self._pending
                                and asyncio.get_running_loop().time() - connected_at
                                > 60
                            ):
                                backoff = self.reconnect_delay
                            # Lifecycle activation/grid changes require a new book.
                            if message.get("type") in {
                                "market_lifecycle_v2",
                                "multivariate_market_lifecycle",
                            }:
                                ticker = message["msg"].get("market_ticker")
                                if (
                                    ticker in self.state.markets
                                    and self.state.markets[ticker].book is None
                                ):
                                    for (
                                        sid,
                                        channel,
                                    ) in self.state.subscriptions.items():
                                        if channel == "orderbook_delta":
                                            command = self._command(
                                                "update_subscription",
                                                {
                                                    "sid": sid,
                                                    "action": "get_snapshot",
                                                    "market_tickers": [ticker],
                                                },
                                            )
                                            await websocket.send(
                                                orjson.dumps(command).decode()
                                            )
                except ArchiveError:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("ws_disconnected", error=str(exc))
                    if self.session_handler:
                        await self.session_handler(
                            "error: " + str(exc), self.session_id
                        )
                finally:
                    # Also executes on clean closes, handler errors, and cancellation;
                    # it precedes backoff, so no stale state is tradable during sleep.
                    self.state.disconnect()
                    self._websocket = None
                    self._pending.clear()
                    if self.session_handler:
                        await self.session_handler("disconnected", self.session_id)
                await asyncio.sleep(backoff)
                backoff = min(
                    self.reconnect_max_delay, max(self.reconnect_delay, backoff * 2)
                )
        finally:
            self._running = False
            self.state.disconnect()

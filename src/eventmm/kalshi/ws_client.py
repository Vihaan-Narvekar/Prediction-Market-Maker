import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import orjson
import structlog
import websockets

from eventmm.kalshi.auth import KalshiAuth

logger = structlog.get_logger()
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


class KalshiWebSocketClient:
    def __init__(
        self,
        ws_url: str,
        auth: KalshiAuth,
        market_tickers: list[str],
        handler: MessageHandler,
        reconnect_delay: float = 2.0,
    ):
        self.ws_url = ws_url
        self.auth = auth
        self.market_tickers = market_tickers
        self.handler = handler
        self.reconnect_delay = reconnect_delay

    async def listen_forever(self) -> None:
        while True:
            try:
                headers = self.auth.sign_headers("GET", self.ws_url)
                async with websockets.connect(
                    self.ws_url,
                    additional_headers=headers,
                ) as websocket:
                    logger.info("ws_connected", markets=self.market_tickers)
                    await websocket.send(orjson.dumps(self._subscription()).decode())

                    async for raw_msg in websocket:
                        await self.handler(orjson.loads(raw_msg))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("ws_disconnected", error=str(exc))
                await asyncio.sleep(self.reconnect_delay)

    def _subscription(self) -> dict[str, Any]:
        return {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": self.market_tickers,
            },
        }

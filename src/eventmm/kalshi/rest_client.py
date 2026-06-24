from typing import Any
import httpx
import structlog

from eventmm.kalshi.auth import KalshiAuth
from eventmm.kalshi.rate_limiter import TokenBucket

logger = structlog.get_logger()


class KalshiRestClient:
    def __init__(
        self,
        base_url: str,
        auth: KalshiAuth | None = None,
        rate_limiter: TokenBucket | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.rate_limiter = rate_limiter
        self.client = httpx.AsyncClient(timeout=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        if self.rate_limiter:
            await self.rate_limiter.acquire()

        url = f"{self.base_url}{path}"
        headers = {}

        if authenticated:
            if self.auth is None:
                raise ValueError("Authenticated request requires KalshiAuth.")
            headers.update(self.auth.sign_headers(method, url))

        logger.info("rest_request_started", method=method, path=path, params=params)

        resp = await self.client.request(method, url, params=params, headers=headers)

        if resp.status_code == 429:
            logger.warning("rate_limit_hit", path=path)
            resp.raise_for_status()

        resp.raise_for_status()

        logger.info(
            "rest_request_completed", method=method, path=path, status=resp.status_code
        )
        return resp.json()

    async def get_markets(
        self,
        *,
        status: str = "open",
        series_ticker: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "status": status,
            "limit": limit,
        }
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor

        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> dict[str, Any]:
        return await self._request("GET", f"/markets/{ticker}")

    async def get_orderbook(
        self, ticker: str, depth: int | None = None
    ) -> dict[str, Any]:
        params = {"depth": depth} if depth is not None else None
        return await self._request("GET", f"/markets/{ticker}/orderbook", params=params)

    async def get_trades(self, ticker: str, limit: int = 1000) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/markets/trades",
            params={"ticker": ticker, "limit": limit},
        )

    async def get_historical_cutoff(self) -> dict[str, Any]:
        return await self._request("GET", "/historical/cutoff")

    async def get_historical_markets(
        self,
        *,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/historical/markets", params=params)

    async def get_historical_trades(
        self,
        *,
        ticker: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
        limit: int = 1000,
        cursor: str | None = None,
        is_block_trade: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        if is_block_trade is not None:
            params["is_block_trade"] = is_block_trade
        return await self._request("GET", "/historical/trades", params=params)

    async def close(self) -> None:
        await self.client.aclose()

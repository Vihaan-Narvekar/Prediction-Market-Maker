from typing import Any
from collections.abc import AsyncIterator

from eventmm.kalshi.http_budget import request_with_budget

import httpx
import structlog

from eventmm.kalshi.auth import KalshiAuth
from eventmm.kalshi.rate_limiter import TokenBucket
from eventmm.schemas.market import normalize_market

logger = structlog.get_logger()


class KalshiRestClient:
    def __init__(
        self,
        base_url: str,
        auth: KalshiAuth | None = None,
        rate_limiter: TokenBucket | None = None,
        timeout: float = 10.0,
        *,
        response_hook=None,
        retry_attempts: int = 4,
        retry_budget: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.rate_limiter = rate_limiter or TokenBucket(5, 5)
        self.response_hook = response_hook
        self.retry_attempts = retry_attempts
        self.retry_budget = retry_budget
        self.client = httpx.AsyncClient(timeout=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if authenticated and self.auth is None:
            raise ValueError("Authenticated request requires KalshiAuth.")
        resp = await request_with_budget(
            self.client,
            method,
            url,
            limiter=self.rate_limiter,
            attempts=self.retry_attempts,
            budget_seconds=self.retry_budget,
            headers_factory=(lambda: self.auth.sign_headers(method, url))
            if self.auth and authenticated
            else None,
            response_hook=self.response_hook,
            params=params,
        )
        data = resp.json()
        if "markets" in data:
            data["markets"] = [normalize_market(market) for market in data["markets"]]
        if "market" in data:
            data["market"] = normalize_market(data["market"])
        return data

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

    async def get_trades(
        self,
        ticker: str,
        limit: int = 1000,
        *,
        cursor: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/markets/trades",
            params={
                k: v
                for k, v in {
                    "ticker": ticker,
                    "limit": limit,
                    "cursor": cursor,
                    "min_ts": min_ts,
                    "max_ts": max_ts,
                }.items()
                if v is not None
            },
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

    async def pages(
        self, fetch, *, max_pages: int = 10000, **kwargs
    ) -> AsyncIterator[dict]:
        """Fail explicitly on looping cursors or a budget-exhausted partial scan."""
        cursor = None
        seen = set()
        for _ in range(max_pages):
            page = await fetch(cursor=cursor, **kwargs)
            yield page
            cursor = page.get("cursor")
            if not cursor:
                return
            if cursor in seen:
                raise RuntimeError("Pagination cursor repeated")
            seen.add(cursor)
        raise RuntimeError("Pagination page budget exhausted")

    async def close(self) -> None:
        await self.client.aclose()

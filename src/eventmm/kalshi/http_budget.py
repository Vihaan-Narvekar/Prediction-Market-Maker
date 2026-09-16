"""Finite GET retry budgets. Every attempt consumes the shared request limiter."""

import asyncio
import random
import time
from email.utils import parsedate_to_datetime

import httpx

from eventmm.kalshi.rate_limiter import TokenBucket


def retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0


async def request_with_budget(
    client,
    method,
    url,
    *,
    limiter: TokenBucket,
    attempts=4,
    budget_seconds=60.0,
    headers_factory=None,
    response_hook=None,
    **kwargs,
) -> httpx.Response:
    if attempts < 1 or budget_seconds <= 0:
        raise ValueError("Positive retry budget required")
    async with asyncio.timeout(budget_seconds):
        for attempt in range(attempts):
            await limiter.acquire()
            headers = headers_factory() if headers_factory else None
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError:
                if method != "GET" or attempt == attempts - 1:
                    raise
                delay = 0.0
            else:
                if response_hook:
                    await response_hook(response)
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response
                if method != "GET" or attempt == attempts - 1:
                    response.raise_for_status()
                delay = retry_after(response.headers.get("Retry-After"))
            await asyncio.sleep(
                max(delay, random.uniform(0.5, 1.0) * min(16, 2**attempt))
            )
    raise RuntimeError("Unreachable retry state")

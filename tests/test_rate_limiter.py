import pytest

from eventmm.kalshi.rate_limiter import TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_acquire():
    bucket = TokenBucket(capacity=1, refill_rate=100)
    await bucket.acquire()
    assert bucket.tokens < 1

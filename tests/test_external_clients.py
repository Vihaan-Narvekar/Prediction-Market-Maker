import httpx
import pytest

from eventmm.external.bls_client import BLSClient
from eventmm.external.noaa_client import MissingNOAATokenError, NOAAClient
from eventmm.external.nws_client import NWSClient


@pytest.mark.asyncio
async def test_nws_point_metadata_path():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/points/40.7128,-74.006"
        assert request.headers["user-agent"] == "eventmm-kalshi research client"
        return httpx.Response(200, json={"properties": {"gridId": "OKX"}})

    client = NWSClient(transport=httpx.MockTransport(handler))
    try:
        data = await client.get_point_metadata(40.7128, -74.0060)
    finally:
        await client.close()

    assert data["properties"]["gridId"] == "OKX"


def test_noaa_requires_token():
    with pytest.raises(MissingNOAATokenError):
        NOAAClient(None)


@pytest.mark.asyncio
async def test_noaa_sends_token_header():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["token"] == "abc"
        assert request.url.path == "/cdo-web/api/v2/datasets"
        return httpx.Response(200, json={"results": []})

    client = NOAAClient("abc", transport=httpx.MockTransport(handler))
    try:
        data = await client.get_datasets()
    finally:
        await client.close()

    assert data == {"results": []}


@pytest.mark.asyncio
async def test_bls_posts_timeseries_request():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/publicAPI/v2/timeseries/data"
        return httpx.Response(200, json={"Results": {"series": []}})

    client = BLSClient(transport=httpx.MockTransport(handler))
    try:
        data = await client.get_timeseries("CUUR0000SA0", 2020, 2026)
    finally:
        await client.close()

    assert "Results" in data

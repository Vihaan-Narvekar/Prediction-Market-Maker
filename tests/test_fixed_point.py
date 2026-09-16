import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal as D

import httpx
import polars as pl
import pytest

from eventmm.backtest.engine import run_threshold_backtest
from eventmm.backtest.events import MarketDataEvent, OrderEvent
from eventmm.backtest.fees import FeeModel
from eventmm.backtest.fills import FillSimulator
from eventmm.backtest.portfolio import Portfolio
from eventmm.backtest.risk import ExposureLimits
from eventmm.data.parquet_writer import BufferedParquetWriter
from eventmm.kalshi.rest_client import KalshiRestClient
from eventmm.lob.book import BinaryOrderBook
from eventmm.lob.features import compute_features
from eventmm.lob.parsing import parse_rest_orderbook
from eventmm.schemas.market import normalize_market, parse_price_ranges, snap_price
from eventmm.schemas.websocket import parse_orderbook_delta, parse_orderbook_snapshot
from eventmm.utils.decimal import decimal_json, dollars_to_cents, to_decimal


def test_subpenny_snapshot_delta_and_features():
    levels = [["0.4201", "1.25"], ["0.4202", "0.01"]]
    yes, no = parse_rest_orderbook(
        {
            "orderbook_fp": {
                "yes_dollars": levels,
                "no_dollars": [["0.5701", "2.50"]],
            }
        }
    )
    assert yes == {D("42.01"): D("1.25"), D("42.02"): D("0.01")}
    snapshot = parse_orderbook_snapshot(
        {
            "seq": 1,
            "msg": {
                "market_ticker": "TEST",
                "yes_dollars_fp": levels,
                "no_dollars_fp": [["0.5701", "2.50"]],
            },
        }
    )
    book = BinaryOrderBook(snapshot.pop("market_ticker"))
    book.apply_snapshot(**snapshot)
    delta = parse_orderbook_delta(
        {
            "seq": 2,
            "msg": {
                "market_ticker": "TEST",
                "side": "yes",
                "price_dollars": "0.4202",
                "delta_fp": "0.24",
            },
        }
    )
    delta.pop("market_ticker")
    book.apply_delta(**delta)
    assert book.yes_bids[D("42.02")] == D("0.25")
    features = compute_features(book)
    assert features.best_yes_ask == D("42.99")
    assert features.yes_midpoint == D("42.505")
    assert features.yes_spread == D("0.97")
    assert features.yes_bid_depth_1 == D("0.25")
    assert isinstance(features.yes_microprice, D)
    assert all(isinstance(p, D) for p in yes | no)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_values_rejected(value):
    with pytest.raises(ValueError):
        to_decimal(value)


def test_dynamic_grid_and_fixed_point_precedence():
    market = normalize_market(
        {
            "yes_bid_dollars": "0.4201",
            "yes_bid": 42,
            "volume_fp": "0.00",
            "volume": 10,
            "open_interest_fp": "1.25",
            "settlement_value_dollars": None,
            "price_level_structure": "future_structure",
            "price_ranges": [
                {"start": "0", "end": "0.1", "step": "0.001"},
                {"start": "0.1", "end": "0.9", "step": "0.01"},
                {"start": "0.9", "end": "1", "step": "0.001"},
            ],
        }
    )
    assert market["yes_bid_dollars"] == D("0.4201")
    assert market["volume"] == D("0")
    assert market["open_interest"] == D("1.25")
    assert market["settlement_value_dollars"] is None
    bands = parse_price_ranges(market)
    assert snap_price(D("0.1001"), bands, "down") == D("0.10")
    assert snap_price(D("0.1001"), bands, "up") == D("0.11")
    assert snap_price(D("0.0991"), bands, "up") == D("0.100")
    assert snap_price(D("0.9001"), bands, "up") == D("0.901")
    with pytest.raises(ValueError):
        snap_price(D("0.42"), [], "up")


def test_fractional_fill_fee_and_settlement():
    ts = datetime(2026, 1, 1)
    order = OrderEvent(
        ts, "TEST", "yes", "buy", "marketable_limit", D("42.02"), D("1.25")
    )
    market = MarketDataEvent(
        ts,
        "TEST",
        D("41.99"),
        D("42.01"),
        None,
        None,
        None,
        None,
        yes_ask_depth=D("0.25"),
    )
    fill = FillSimulator(FeeModel(include_fees=False)).simulate_taker_fill(
        order, market
    )
    assert fill is not None
    assert fill.quantity == D("0.25")
    assert fill.requested_quantity == D("1.25")
    portfolio = Portfolio()
    portfolio.apply_fill(fill)
    assert portfolio.settle("TEST", 1) == D("14.4975")
    assert portfolio.positions["TEST"].yes_cash_flow_cents == D("10.5025")
    assert FeeModel().estimate_fee_cents(D("42.01"), D("0.25"), "taker") == D("1")
    limits = ExposureLimits(D("0.50"), D("0.50"))
    limits.record(
        market_ticker="TEST", event_ticker="EVENT", signed_quantity=fill.quantity
    )
    assert limits.market_positions["TEST"] == D("0.25")
    assert not limits.allows(
        market_ticker="TEST", event_ticker="EVENT", signed_quantity=D("0.26")
    )


def test_decimal_storage_roundtrip(tmp_path):
    writer = BufferedParquetWriter(tmp_path, "features")
    book = BinaryOrderBook("TEST", {D("42.01"): D("1.25")}, {D("57.01"): D("2.50")})
    row = asdict(compute_features(book))
    writer.append(row)
    path = writer.flush()
    restored = pl.read_parquet(path).to_dicts()[0]
    assert restored["best_yes_bid"] == D("42.01")
    assert restored["yes_bid_depth_1"] == D("1.25")
    assert restored["yes_microprice"] == row["yes_microprice"]
    assert (
        json.loads(
            json.dumps({"price": dollars_to_cents("0.4201")}, default=decimal_json)
        )["price"]
        == "42.0100"
    )


@pytest.mark.asyncio
async def test_rest_markets_without_cent_fields():
    payload = {
        "ticker": "TEST",
        "yes_bid_dollars": "0.4201",
        "volume_fp": "1.25",
        "price_level_structure": "deci_cent",
        "price_ranges": [{"start": "0", "end": "1", "step": "0.001"}],
    }
    client = KalshiRestClient("https://example.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"markets": [payload]})
        )
    )
    try:
        result = await client.get_markets()
    finally:
        await client.close()
    assert result["markets"][0]["yes_bid_dollars"] == D("0.4201")
    assert result["markets"][0]["volume"] == D("1.25")


def test_backtest_fractional_config_and_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "datasets" / "test"
    data.mkdir(parents=True)
    pl.DataFrame(
        [
            {
                "market_ticker": "TEST",
                "as_of_ts": datetime(2026, 1, 1),
                "label": 1,
                "best_yes_bid": D("41.99"),
                "best_yes_ask": D("42.01"),
                "market_mid": D("42.00"),
                "p_model": 0.6,
                "yes_ask_depth_1": D("0.25"),
            }
        ]
    ).write_parquet(data / "part.parquet")
    output = run_threshold_backtest(
        {
            "dataset": "test",
            "strategy": {"quantity": "1.25"},
            "fees": {"include_fees": False},
            "risk": {"max_market_position": "1.5", "max_event_exposure": "1.5"},
        },
        data_dir=tmp_path / "datasets",
    )
    assert pl.read_parquet(output / "fills.parquet")["quantity"][0] == D("0.25")
    assert D(json.loads((output / "metrics.json").read_text())["net_pnl"]) == D(
        "14.4975"
    )


def test_empty_fixed_point_book_takes_precedence():
    assert parse_rest_orderbook(
        {"orderbook_fp": {}, "orderbook": {"yes_dollars": [["0.5", "1"]]}}
    ) == ({}, {})
    snapshot = parse_orderbook_snapshot(
        {
            "msg": {
                "market_ticker": "TEST",
                "yes_dollars_fp": [],
                "yes_dollars": [["0.5", "1"]],
            }
        }
    )
    assert snapshot["yes_bids"] == {}

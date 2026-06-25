from datetime import datetime, timezone

import polars as pl

from eventmm.monitoring.collector_reports import (
    build_collector_health,
    build_orderbook_audit,
    parse_since,
)


def test_parse_since_hours():
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)

    assert parse_since("24h", now=now) == datetime(2026, 6, 24, 12, tzinfo=timezone.utc)


def test_collector_health_and_orderbook_audit(tmp_path):
    processed = tmp_path / "processed"
    universe_dir = processed / "market_universes" / "kxhighny_weather_universe"
    book_dir = processed / "book_features"
    forecast_dir = processed / "external" / "nws_hourly_forecasts"
    label_dir = processed / "labels" / "market_outcomes"
    for path in (universe_dir, book_dir, forecast_dir, label_dir):
        path.mkdir(parents=True)

    pl.DataFrame(
        {
            "market_ticker": ["KXHIGHNY-1", "KXHIGHNY-2", "KXHIGHNY-3"],
            "series_ticker": ["KXHIGHNY", "KXHIGHNY", "KXHIGHNY"],
            "close_time": [
                "2026-06-25T20:00:00Z",
                "2026-06-25T20:00:00Z",
                "2026-06-25T20:00:00Z",
            ],
        }
    ).write_parquet(universe_dir / "part-0.parquet")
    pl.DataFrame(
        {
            "market_ticker": ["KXHIGHNY-1", "KXHIGHNY-2", "KXHIGHNY-3"],
            "as_of_ts": [
                datetime(2026, 6, 25, 10, tzinfo=timezone.utc),
                datetime(2026, 6, 25, 10, tzinfo=timezone.utc),
                datetime(2026, 6, 25, 10, tzinfo=timezone.utc),
            ],
            "best_yes_bid": [40, 20, None],
            "best_no_bid": [55, None, None],
            "market_mid": [42.5, None, None],
            "market_spread": [5, None, None],
            "market_depth_imbalance": [0.2, None, None],
        }
    ).write_parquet(book_dir / "part-0.parquet")
    pl.DataFrame(
        {
            "location": ["NYC"],
            "forecast_issue_ts": [datetime(2026, 6, 25, 9, tzinfo=timezone.utc)],
            "forecast_temperature": [84],
        }
    ).write_parquet(forecast_dir / "part-0.parquet")
    pl.DataFrame(
        {
            "market_ticker": ["KXHIGHNY-1"],
            "settlement_time": [datetime(2026, 6, 25, 21, tzinfo=timezone.utc)],
            "label": [1],
        }
    ).write_parquet(label_dir / "part-0.parquet")

    health = build_collector_health(tmp_path, series="KXHIGHNY", since="all")
    audit = build_orderbook_audit(tmp_path, series="KXHIGHNY", since="all")

    assert health.raw_market_rows == 3
    assert health.normalized_orderbook_rows == 3
    assert health.unique_markets_with_midpoint == 1
    assert audit.empty_books == 1
    assert audit.one_sided_books == 1
    assert audit.two_sided_books == 1
    assert audit.valid_midpoint_rows == 1

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl


def read_parquet_dir(path: Path) -> pl.DataFrame:
    files = sorted(path.glob("*.parquet")) if path.exists() else []
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(file) for file in files], how="diagonal_relaxed")


def parse_since(value: str, now: datetime | None = None) -> datetime | None:
    normalized = value.strip().lower()
    if normalized in {"", "all"}:
        return None
    now = now or datetime.now(timezone.utc)
    if normalized.endswith("h"):
        return now - timedelta(hours=float(normalized[:-1]))
    if normalized.endswith("d"):
        return now - timedelta(days=float(normalized[:-1]))
    parsed = datetime.fromisoformat(normalized.replace("z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _filter_since(
    df: pl.DataFrame, column: str, since_ts: datetime | None
) -> pl.DataFrame:
    if since_ts is None or len(df) == 0 or column not in df.columns:
        return df
    return df.with_columns(pl.col(column).cast(pl.Datetime(time_zone="UTC"))).filter(
        pl.col(column) >= since_ts
    )


def _filter_series(df: pl.DataFrame, series: str) -> pl.DataFrame:
    if len(df) == 0:
        return df
    if "series_ticker" in df.columns:
        filtered = df.filter(pl.col("series_ticker") == series)
        if len(filtered) > 0:
            return filtered
    if "market_ticker" in df.columns:
        return df.filter(pl.col("market_ticker").str.starts_with(series))
    if "event_ticker" in df.columns:
        return df.filter(pl.col("event_ticker").str.starts_with(series))
    return df


def _latest(df: pl.DataFrame, column: str) -> str | None:
    if len(df) == 0 or column not in df.columns:
        return None
    value = df.select(pl.col(column).max()).item()
    return str(value) if value is not None else None


def _non_null_count(df: pl.DataFrame, column: str) -> int:
    return df.filter(pl.col(column).is_not_null()).height if column in df.columns else 0


def _median(df: pl.DataFrame, column: str) -> float | None:
    if len(df) == 0 or column not in df.columns:
        return None
    value = df.select(pl.col(column).median()).item()
    return float(value) if value is not None else None


def _median_top_depth(df: pl.DataFrame) -> float | None:
    if len(df) == 0:
        return None
    if {"yes_bid_depth_1", "yes_ask_depth_1"}.issubset(df.columns):
        value = df.select(
            (
                pl.col("yes_bid_depth_1").fill_null(0)
                + pl.col("yes_ask_depth_1").fill_null(0)
            ).median()
        ).item()
        return float(value) if value is not None else None
    return None


@dataclass(frozen=True)
class CollectorHealth:
    raw_market_rows: int
    raw_orderbook_rows: int
    normalized_orderbook_rows: int
    forecast_snapshot_rows: int
    label_rows: int
    unique_markets_seen: int
    unique_markets_with_nonempty_books: int
    unique_markets_with_midpoint: int
    two_sided_book_pct: float
    valid_midpoint_pct: float
    forecast_coverage_pct: float
    latest_market_as_of: str | None
    latest_orderbook_as_of: str | None
    latest_forecast_as_of: str | None
    latest_label_as_of: str | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class OrderBookAudit:
    total_books: int
    empty_books: int
    one_sided_books: int
    two_sided_books: int
    invalid_crossed_books: int
    valid_midpoint_rows: int
    median_spread_cents: float | None
    median_top_depth: float | None
    markets_with_snapshots: int
    markets_with_no_snapshots: int
    top_markets: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _book_state(book_features: pl.DataFrame) -> pl.DataFrame:
    if len(book_features) == 0:
        return book_features
    df = book_features
    has_yes_bid = (
        pl.col("best_yes_bid").is_not_null()
        if "best_yes_bid" in df.columns
        else pl.lit(False)
    )
    has_no_bid = (
        pl.col("best_no_bid").is_not_null()
        if "best_no_bid" in df.columns
        else pl.lit(False)
    )
    has_midpoint = (
        pl.col("market_mid").is_not_null()
        if "market_mid" in df.columns
        else pl.lit(False)
    )
    spread = pl.col("market_spread") if "market_spread" in df.columns else pl.lit(None)
    return df.with_columns(
        has_yes_bid.alias("has_yes_bid"),
        has_no_bid.alias("has_no_bid"),
        has_midpoint.alias("has_midpoint"),
        (has_yes_bid | has_no_bid).alias("has_nonempty_book"),
        (has_yes_bid & has_no_bid).alias("has_two_sided_book"),
        (has_yes_bid ^ has_no_bid).alias("has_one_sided_book"),
        (spread < 0).fill_null(False).alias("has_invalid_crossed_book"),
    )


def build_collector_health(
    data_dir: Path,
    *,
    series: str,
    since: str = "24h",
) -> CollectorHealth:
    since_ts = parse_since(since)
    processed = data_dir / "processed"
    market_rows = read_parquet_dir(
        processed / "market_universes" / f"{series.lower()}_weather_universe"
    )
    market_rows = _filter_series(market_rows, series)
    book_rows = _filter_series(read_parquet_dir(processed / "book_features"), series)
    book_rows = _filter_since(book_rows, "as_of_ts", since_ts)
    book_rows = _book_state(book_rows)
    forecasts = read_parquet_dir(processed / "external" / "nws_hourly_forecasts")
    forecasts = _filter_since(forecasts, "forecast_issue_ts", since_ts)
    labels = _filter_series(
        read_parquet_dir(processed / "labels" / "market_outcomes"), series
    )

    unique_markets_seen = (
        market_rows.select("market_ticker").n_unique()
        if "market_ticker" in market_rows.columns
        else 0
    )
    unique_nonempty = (
        book_rows.filter(pl.col("has_nonempty_book")).select("market_ticker").n_unique()
        if len(book_rows) and "market_ticker" in book_rows.columns
        else 0
    )
    unique_midpoint = (
        book_rows.filter(pl.col("has_midpoint")).select("market_ticker").n_unique()
        if len(book_rows) and "market_ticker" in book_rows.columns
        else 0
    )
    two_sided = (
        book_rows.filter(pl.col("has_two_sided_book")).height if len(book_rows) else 0
    )
    midpoint = book_rows.filter(pl.col("has_midpoint")).height if len(book_rows) else 0
    forecast_markets = (
        book_rows.filter(pl.col("market_ticker").is_not_null()).height
        if len(book_rows) and "market_ticker" in book_rows.columns
        else 0
    )
    return CollectorHealth(
        raw_market_rows=len(market_rows),
        raw_orderbook_rows=len(book_rows),
        normalized_orderbook_rows=len(book_rows),
        forecast_snapshot_rows=len(forecasts),
        label_rows=len(labels),
        unique_markets_seen=unique_markets_seen,
        unique_markets_with_nonempty_books=unique_nonempty,
        unique_markets_with_midpoint=unique_midpoint,
        two_sided_book_pct=(two_sided / len(book_rows) * 100)
        if len(book_rows)
        else 0.0,
        valid_midpoint_pct=(midpoint / len(book_rows) * 100) if len(book_rows) else 0.0,
        forecast_coverage_pct=100.0 if len(forecasts) and forecast_markets else 0.0,
        latest_market_as_of=_latest(market_rows, "close_time"),
        latest_orderbook_as_of=_latest(book_rows, "as_of_ts"),
        latest_forecast_as_of=_latest(forecasts, "forecast_issue_ts"),
        latest_label_as_of=_latest(labels, "settlement_time")
        or _latest(labels, "created_ts"),
    )


def build_orderbook_audit(
    data_dir: Path,
    *,
    series: str,
    since: str = "24h",
) -> OrderBookAudit:
    since_ts = parse_since(since)
    market_rows = read_parquet_dir(
        data_dir
        / "processed"
        / "market_universes"
        / f"{series.lower()}_weather_universe"
    )
    market_rows = _filter_series(market_rows, series)
    book_rows = _filter_series(
        read_parquet_dir(data_dir / "processed" / "book_features"), series
    )
    book_rows = _filter_since(book_rows, "as_of_ts", since_ts)
    book_rows = _book_state(book_rows)

    top_markets: list[dict[str, Any]] = []
    if len(book_rows) and "market_ticker" in book_rows.columns:
        top_markets = (
            book_rows.group_by("market_ticker")
            .len()
            .sort("len", descending=True)
            .head(20)
            .rename({"len": "snapshots"})
            .to_dicts()
        )

    markets_seen = (
        set(market_rows["market_ticker"].to_list())
        if "market_ticker" in market_rows.columns
        else set()
    )
    markets_with_books = (
        set(book_rows["market_ticker"].drop_nulls().to_list())
        if "market_ticker" in book_rows.columns
        else set()
    )
    return OrderBookAudit(
        total_books=len(book_rows),
        empty_books=book_rows.filter(~pl.col("has_nonempty_book")).height
        if len(book_rows)
        else 0,
        one_sided_books=book_rows.filter(pl.col("has_one_sided_book")).height
        if len(book_rows)
        else 0,
        two_sided_books=book_rows.filter(pl.col("has_two_sided_book")).height
        if len(book_rows)
        else 0,
        invalid_crossed_books=book_rows.filter(
            pl.col("has_invalid_crossed_book")
        ).height
        if len(book_rows)
        else 0,
        valid_midpoint_rows=book_rows.filter(pl.col("has_midpoint")).height
        if len(book_rows)
        else 0,
        median_spread_cents=_median(book_rows, "market_spread"),
        median_top_depth=_median_top_depth(book_rows),
        markets_with_snapshots=len(markets_with_books),
        markets_with_no_snapshots=len(markets_seen - markets_with_books),
        top_markets=top_markets,
    )

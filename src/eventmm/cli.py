import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import typer
import yaml
from rich.console import Console
from rich.table import Table

from eventmm.backtest.data_loader import load_backtest_dataset, summarize_backtest_data
from eventmm.backtest.engine import run_threshold_backtest
from eventmm.config.logging import configure_logging
from eventmm.config.settings import settings
from eventmm.contracts.weather import parse_weather_contracts
from eventmm.datasets.coverage import (
    compute_column_coverage,
    compute_feature_set_coverage,
)
from eventmm.datasets.labels import build_market_labels
from eventmm.datasets.manifest import verify_dataset_manifest, write_dataset_manifest
from eventmm.datasets.registry import DatasetRegistry
from eventmm.datasets.validation import (
    DatasetValidationError,
    validate_weather_dataset,
    weather_validation_summary,
)
from eventmm.external.bls_client import BLSClient
from eventmm.external.forecast_versions import (
    append_forecast_version,
    build_nws_forecast_version_row,
)
from eventmm.external.fred_client import FREDClient
from eventmm.external.noaa_client import NOAAClient
from eventmm.external.nws_client import NWSClient
from eventmm.kalshi.rest_client import KalshiRestClient
from eventmm.lob.book import BinaryOrderBook
from eventmm.lob.features import compute_features
from eventmm.lob.parsing import parse_rest_orderbook
from eventmm.modeling.baselines import (
    forecast_threshold_probability,
    market_midpoint_probability,
    microprice_probability,
)
from eventmm.modeling.dataset import load_modeling_dataset
from eventmm.modeling.evaluation import calibration_table, evaluate_probabilities
from eventmm.modeling.features import FEATURE_SETS
from eventmm.modeling.models import make_logistic_regression_model
from eventmm.modeling.walk_forward import evaluate_walk_forward
from eventmm.modeling.registry import ModelRegistry
from eventmm.monitoring.collector_reports import (
    build_collector_health,
    build_orderbook_audit,
    build_weather_coverage,
    check_collector_freshness,
)
from eventmm.pipelines.weather_collector import WeatherCollectorPipeline
from eventmm.reports.calibration_report import write_calibration_report
from eventmm.reports.model_report import write_model_report
from eventmm.research.baselines import add_weather_baseline_features
from eventmm.research.forecast_revisions import add_forecast_revision_features
from eventmm.research.partitions import (
    build_monotonicity_violations,
    build_partition_features,
    simulate_partition_basket,
)
from eventmm.signals.edge import add_edge_columns

app = typer.Typer(help="Kalshi event market-making research tools.")
datasets_app = typer.Typer(help="Dataset registry commands.")
models_app = typer.Typer(help="Part 3 fair-value modeling commands.")
backtest_app = typer.Typer(help="Event-driven backtesting commands.")
collector_app = typer.Typer(help="Live collector observability commands.")
orderbooks_app = typer.Typer(help="Order-book audit commands.")
research_app = typer.Typer(
    help="Structural and market microstructure research commands."
)
app.add_typer(datasets_app, name="datasets")
app.add_typer(models_app, name="models")
app.add_typer(backtest_app, name="backtest")
app.add_typer(collector_app, name="collector")
app.add_typer(orderbooks_app, name="orderbooks")
app.add_typer(research_app, name="research")
console = Console()

WEATHER_LOCATIONS: dict[str, dict[str, Any]] = {
    "NYC": {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "stations": ["USW00094728", "USW00014732", "USW00094789"],
    },
    "CHICAGO": {
        "latitude": 41.8781,
        "longitude": -87.6298,
        "stations": ["KMDW", "KORD"],
    },
    "MIAMI": {"latitude": 25.7617, "longitude": -80.1918, "stations": ["KMIA"]},
    "AUSTIN": {"latitude": 30.2672, "longitude": -97.7431, "stations": ["KAUS"]},
    "BOSTON": {"latitude": 42.3601, "longitude": -71.0589, "stations": ["KBOS"]},
}


def _client() -> KalshiRestClient:
    return KalshiRestClient(settings.rest_base_url)


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    return path


def _load_contract_overrides(
    path: Path = Path("configs/contract_overrides.yaml"),
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("contracts", data) or {}


def _read_parquet_dir(path: Path) -> pl.DataFrame | None:
    files = sorted(path.glob("*.parquet"))
    if not files:
        return None
    return pl.concat([pl.read_parquet(file) for file in files], how="diagonal_relaxed")


def _parquet_paths(path: Path) -> list[Path]:
    return sorted(path.glob("*.parquet")) if path.exists() else []


def _registry() -> DatasetRegistry:
    return DatasetRegistry(settings.data_dir / "registry")


def _model_dataset_dir() -> Path:
    return settings.data_dir / "processed" / "datasets"


async def _fetch_markets(
    series: str | None, status: str, limit: int
) -> list[dict[str, Any]]:
    statuses = ["open", "closed", "settled"] if status == "all" else [status]
    markets: list[dict[str, Any]] = []
    client = _client()
    try:
        for item_status in statuses:
            data = await client.get_markets(
                status=item_status,
                series_ticker=series,
                limit=limit,
            )
            markets.extend(data.get("markets", []))
    finally:
        await client.close()
    seen: set[str] = set()
    deduped = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if ticker and ticker not in seen:
            seen.add(ticker)
            deduped.append(market)
    return deduped


def _write_market_universe(series: str, markets: list[dict[str, Any]]) -> Path:
    rows = [
        {
            "market_ticker": market.get("ticker"),
            "event_ticker": market.get("event_ticker"),
            "series_ticker": market.get("series_ticker"),
            "title": market.get("title"),
            "status": market.get("status"),
            "close_time": market.get("close_time"),
            "expiration_time": market.get("expiration_time"),
            "volume": market.get("volume"),
            "open_interest": market.get("open_interest"),
        }
        for market in markets
    ]
    out_dir = (
        settings.data_dir
        / "processed"
        / "market_universes"
        / f"{series.lower()}_weather_universe"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"part-{_now_slug()}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    return out_path


def _write_contract_failure_report(
    series: str, markets: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> Path:
    title_by_ticker = {market.get("ticker"): market.get("title") for market in markets}
    failures = [row for row in rows if row.get("parse_status") != "parsed"]
    report_path = Path("reports") / "part_2_weather_contract_parse_failures.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Part 2 Weather Contract Parse Failures",
        "",
        f"Series: {series}",
        f"Total markets parsed: {len(rows)}",
        f"Failed parses: {len(failures)}",
        "",
    ]
    for row in failures:
        ticker = row.get("market_ticker")
        lines.extend(
            [
                f"## {ticker}",
                "",
                f"- title: {title_by_ticker.get(ticker) or ''}",
                f"- reason_failed: {row.get('parse_error') or ''}",
                "- manual interpretation: TODO",
                "- parser change needed: TODO",
                "",
            ]
        )
    if not failures:
        lines.append("No parse failures found.")
    report_path.write_text("\n".join(lines))
    return report_path


def _normalize_book_feature_columns(df: pl.DataFrame) -> pl.DataFrame:
    renames = {
        "ts": "as_of_ts",
        "yes_midpoint": "market_mid",
        "yes_microprice": "market_microprice",
        "yes_spread": "market_spread",
        "imbalance_1": "market_depth_imbalance",
    }
    existing = {
        old: new
        for old, new in renames.items()
        if old in df.columns and new not in df.columns
    }
    return df.rename(existing) if existing else df


async def _bootstrap_market_features(contracts: pl.DataFrame) -> pl.DataFrame:
    parsed = contracts.filter(pl.col("parse_status") == "parsed")
    rows: list[dict[str, Any]] = []
    client = _client()
    try:
        for contract in parsed.to_dicts():
            ticker = contract["market_ticker"]
            row = {
                "market_ticker": ticker,
                "as_of_ts": datetime.now(timezone.utc),
                "close_time": contract.get("close_time"),
                "expiration_time": contract.get("expiration_time"),
                "best_yes_bid": None,
                "best_yes_ask": None,
                "best_no_bid": None,
                "best_no_ask": None,
                "market_mid": None,
                "market_microprice": None,
                "market_spread": None,
                "market_depth_imbalance": None,
                "yes_bid_depth_1": None,
                "yes_ask_depth_1": None,
                "no_bid_depth_1": None,
                "no_ask_depth_1": None,
            }
            try:
                raw = await client.get_orderbook(ticker)
                yes_bids, no_bids = parse_rest_orderbook(raw)
                book = BinaryOrderBook(ticker)
                book.apply_snapshot(
                    yes_bids=yes_bids, no_bids=no_bids, ts=row["as_of_ts"]
                )
                features = compute_features(
                    book, environment=settings.data_environment.value
                )
                row.update(
                    {
                        "best_yes_bid": features.best_yes_bid,
                        "best_yes_ask": features.best_yes_ask,
                        "best_no_bid": features.best_no_bid,
                        "best_no_ask": features.best_no_ask,
                        "market_mid": features.yes_midpoint,
                        "market_microprice": features.yes_microprice,
                        "market_spread": features.yes_spread,
                        "market_depth_imbalance": features.imbalance_1,
                        "yes_bid_depth_1": features.yes_bid_depth_1,
                        "yes_ask_depth_1": features.yes_ask_depth_1,
                        "no_bid_depth_1": features.yes_ask_depth_1,
                        "no_ask_depth_1": features.yes_bid_depth_1,
                    }
                )
            except Exception as exc:
                row["feature_error"] = str(exc)
            rows.append(row)
            await asyncio.sleep(0.08)
    finally:
        await client.close()
    return pl.DataFrame(rows)


async def _collect_kalshi_market_metadata(series: str) -> None:
    markets = await _fetch_markets(series=series, status="all", limit=1000)
    out_path = _write_market_universe(series, markets)
    console.print(f"Wrote market metadata universe to {out_path}")


async def _collect_current_orderbook_snapshots(series: str) -> None:
    markets = await _fetch_markets(series=series, status="open", limit=1000)
    specs = parse_weather_contracts(markets)
    rows = []
    market_by_ticker = {market.get("ticker"): market for market in markets}
    for spec in specs:
        row = spec.to_row()
        market = market_by_ticker.get(spec.market_ticker, {})
        row.update(
            {
                "close_time": market.get("close_time"),
                "expiration_time": market.get("expiration_time"),
            }
        )
        rows.append(row)
    contracts = pl.DataFrame(rows) if rows else pl.DataFrame()
    features = await _bootstrap_market_features(contracts)
    out_dir = settings.data_dir / "processed" / "book_features"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"collector-{series}-{_now_slug()}.parquet"
    features.write_parquet(out_path)
    console.print(
        f"Wrote {len(features)} current order-book feature rows to {out_path}"
    )


def _write_validation_report(
    name: str, df: pl.DataFrame, stats: dict[str, int], error: str | None
) -> Path:
    report_path = Path("reports") / "part_2_weather_nyc_main_validation.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    start = (
        str(df.select(pl.col("as_of_ts").min()).item())
        if "as_of_ts" in df.columns and len(df)
        else ""
    )
    end = (
        str(df.select(pl.col("as_of_ts").max()).item())
        if "as_of_ts" in df.columns and len(df)
        else ""
    )
    lines = [
        "# Part 2 Weather NYC Main Validation",
        "",
        f"Dataset name: {name}",
        f"Rows: {stats.get('rows', 0)}",
        f"Markets: {stats.get('markets', 0)}",
        f"Start: {start}",
        f"End: {end}",
        "",
        "## Validation",
        f"- duplicate market_ticker/as_of_ts rows: {stats.get('duplicate_market_timestamp_rows', 0)}",
        f"- future forecast leakage rows: {stats.get('future_forecast_leakage_rows', 0)}",
        f"- missing labels: {stats.get('missing_labels', 0)}",
        f"- missing forecast rows: {stats.get('missing_forecast_rows', 0)}",
        f"- missing thresholds: {stats.get('missing_thresholds', 0)}",
        f"- impossible temperatures: {stats.get('impossible_temperatures', 0)}",
        f"- unresolved markets: {stats.get('unresolved_markets', 0)}",
        "",
        "Dataset passed validation."
        if error is None
        else f"Dataset failed validation because: {error}",
    ]
    report_path.write_text("\n".join(lines))
    return report_path


def _write_part2_report(name: str, stats: dict[str, int]) -> Path:
    report_path = Path("reports") / "part_2_weather_exogenous_dataset.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# Part 2: Weather Exogenous Data and Outcome Dataset",
                "",
                "## Objective",
                "Build a no-leakage research dataset joining Kalshi weather markets to NWS forecasts, NOAA observations, and settlement labels.",
                "",
                "## Data Sources",
                "- Kalshi market metadata and order-book snapshot features",
                "- NWS hourly forecasts",
                "- NOAA daily observations",
                "",
                "## Contract Parsing",
                "Weather market titles are converted into structured threshold contracts with location, date, threshold, unit, and comparison operator.",
                "",
                "## As-Of Join Logic",
                "Forecast rows are joined only when `forecast_issue_ts <= as_of_ts`.",
                "",
                "## Dataset Validation",
                f"- dataset: {name}",
                f"- rows: {stats.get('rows', 0)}",
                f"- markets: {stats.get('markets', 0)}",
                f"- future leakage rows: {stats.get('future_forecast_leakage_rows', 0)}",
                f"- missing labels: {stats.get('missing_labels', 0)}",
                f"- missing forecast rows: {stats.get('missing_forecast_rows', 0)}",
                "",
                "## Next Step",
                "Part 3: fair-value modeling and calibration.",
            ]
        )
    )
    return report_path


@app.callback()
def main() -> None:
    configure_logging(settings.log_level)


@app.command()
def markets(
    status: str = "open",
    limit: int = 20,
    series: str | None = None,
    min_volume: int = 0,
) -> None:
    asyncio.run(
        _markets(status=status, limit=limit, series=series, min_volume=min_volume)
    )


async def _markets(
    status: str, limit: int, series: str | None, min_volume: int
) -> None:
    markets = await _fetch_markets(series=series, status=status, limit=limit)

    table = Table(title="Kalshi Markets")
    table.add_column("Ticker")
    table.add_column("Title")
    table.add_column("Category")
    table.add_column("Volume", justify="right")
    table.add_column("Open Interest", justify="right")
    table.add_column("Close Time")

    displayed_markets = []
    for market in markets:
        if (market.get("volume") or 0) < min_volume:
            continue
        displayed_markets.append(market)
        table.add_row(
            str(market.get("ticker") or ""),
            str(market.get("title") or "")[:80],
            str(market.get("category") or ""),
            str(market.get("volume") or 0),
            str(market.get("open_interest") or 0),
            str(market.get("close_time") or ""),
        )

    console.print(table)
    if series:
        out_path = _write_market_universe(series, displayed_markets)
        console.print(f"Wrote market universe to {out_path}")


@app.command()
def snapshot(market: str) -> None:
    asyncio.run(_snapshot(market))


@app.command("inspect-book")
def inspect_book(market: str) -> None:
    asyncio.run(_inspect_book(market))


@app.command()
def features(market: str) -> None:
    asyncio.run(_features(market))


async def _build_book(market: str) -> BinaryOrderBook:
    client = _client()
    try:
        raw = await client.get_orderbook(market)
    finally:
        await client.close()

    yes_bids, no_bids = parse_rest_orderbook(raw)
    book = BinaryOrderBook(market)
    book.apply_snapshot(yes_bids=yes_bids, no_bids=no_bids)
    return book


async def _snapshot(market: str) -> None:
    book = await _build_book(market)
    features = compute_features(book, environment=settings.data_environment.value)
    console.print(asdict(features))


async def _features(market: str) -> None:
    await _snapshot(market)


async def _inspect_book(market: str) -> None:
    book = await _build_book(market)

    table = Table(title=f"Reconstructed book: {market}")
    table.add_column("Side")
    table.add_column("Price Cents", justify="right")
    table.add_column("Quantity", justify="right")

    for price, quantity in sorted(book.yes_bids.items(), reverse=True):
        table.add_row("YES bid", str(price), str(quantity))
    for price, quantity in sorted(book.yes_asks().items()):
        table.add_row("YES ask", str(price), str(quantity))
    for price, quantity in sorted(book.no_bids.items(), reverse=True):
        table.add_row("NO bid", str(price), str(quantity))
    for price, quantity in sorted(book.no_asks().items()):
        table.add_row("NO ask", str(price), str(quantity))

    console.print(table)


@app.command("collect-nws-forecast")
def collect_nws_forecast(location: str = "NYC") -> None:
    asyncio.run(_collect_nws_forecast(location))


@app.command("archive-nws-forecast")
def archive_nws_forecast(
    locations: str = "NYC",
    interval_minutes: float = 30.0,
    iterations: int = 1,
) -> None:
    asyncio.run(_archive_nws_forecast(locations, interval_minutes, iterations))


async def _archive_nws_forecast(
    locations: str,
    interval_minutes: float,
    iterations: int,
) -> None:
    location_list = [
        location.strip().upper()
        for location in locations.split(",")
        if location.strip()
    ]
    for iteration in range(iterations):
        for location in location_list:
            await _collect_nws_forecast(location)
        if iteration < iterations - 1:
            await asyncio.sleep(interval_minutes * 60)


@app.command("collect-weather")
def collect_weather(series: str, start: str, end: str) -> None:
    console.print(
        "Weather collection is split into source-specific commands. "
        "Running NWS forecast collection for configured weather locations."
    )
    for location in WEATHER_LOCATIONS:
        asyncio.run(_collect_nws_forecast(location))
    console.print(
        f"Collected weather source snapshot for {series} between {start} and {end}."
    )


@app.command("run-weather-collector")
def run_weather_collector(
    locations: str = "NYC",
    series: str = "KXHIGHNY",
    interval_minutes: float = 15.0,
    iterations: int = 1,
) -> None:
    location_list = [
        location.strip().upper()
        for location in locations.split(",")
        if location.strip()
    ]

    async def collect_markets() -> None:
        await _collect_kalshi_market_metadata(series)
        await _parse_contracts(series, apply_overrides=True)

    async def collect_book_features() -> None:
        await _collect_current_orderbook_snapshots(series)

    async def collect_labels_once() -> None:
        await _build_labels(series)

    pipeline = WeatherCollectorPipeline(
        locations=location_list,
        series=series,
        interval_minutes=interval_minutes,
        collect_markets=collect_markets,
        collect_book_features=collect_book_features,
        collect_forecasts=_collect_nws_forecast,
        collect_noaa_observations=_collect_noaa_daily,
        collect_labels=collect_labels_once,
    )
    asyncio.run(pipeline.run(iterations=iterations))


async def _collect_nws_forecast(location: str) -> None:
    collection_ts = datetime.now(timezone.utc)
    loc = WEATHER_LOCATIONS[location.upper()]
    client = NWSClient()
    try:
        point = await client.get_point_metadata(loc["latitude"], loc["longitude"])
        props = point["properties"]
        grid_id = props["gridId"]
        grid_x = props["gridX"]
        grid_y = props["gridY"]
        forecast = await client.get_hourly_forecast(grid_id, grid_x, grid_y)
    finally:
        await client.close()

    raw_path = _write_json(
        settings.data_dir
        / "raw"
        / "external"
        / "nws"
        / f"location={location.upper()}"
        / f"{_now_slug()}.json",
        {"point": point, "forecast": forecast},
    )
    version_path = append_forecast_version(
        settings.data_dir,
        build_nws_forecast_version_row(
            location=location,
            collection_ts=collection_ts,
            raw_response_path=raw_path,
            forecast_payload=forecast,
        ),
    )

    rows = []
    for period in forecast.get("properties", {}).get("periods", []):
        rows.append(
            {
                "location": location.upper(),
                "collection_ts": collection_ts,
                "forecast_issue_ts": collection_ts,
                "forecast_start_ts": period.get("startTime"),
                "forecast_end_ts": period.get("endTime"),
                "forecast_valid_ts": period.get("startTime"),
                "forecast_date": str(period.get("startTime", ""))[:10],
                "forecast_temperature": period.get("temperature"),
                "temperature_unit": period.get("temperatureUnit"),
                "short_forecast": period.get("shortForecast"),
                "source": "nws_api",
                "raw_path": str(raw_path),
                "forecast_version_path": str(version_path),
            }
        )

    out_dir = settings.data_dir / "processed" / "external" / "nws_hourly_forecasts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"location={location.upper()}-{_now_slug()}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    console.print(f"Wrote {len(rows)} NWS forecast rows to {out_path}")
    console.print(f"Wrote forecast version row to {version_path}")


@app.command("collect-noaa-daily")
def collect_noaa_daily(
    location: str = typer.Option(...),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
) -> None:
    asyncio.run(_collect_noaa_daily(location, start, end))


async def _collect_noaa_daily(location: str, start: str, end: str) -> None:
    loc = WEATHER_LOCATIONS[location.upper()]
    client = NOAAClient(settings.noaa_cdo_token)
    rows = []
    try:
        for station in loc["stations"]:
            payload = await client.get_daily_data(
                dataset_id="GHCND",
                station_id=f"GHCND:{station}",
                start_date=start,
                end_date=end,
                datatype_ids=["TMAX"],
            )
            _write_json(
                settings.data_dir
                / "raw"
                / "external"
                / "noaa"
                / f"location={location.upper()}"
                / f"station={station}-{_now_slug()}.json",
                payload,
            )
            for item in payload.get("results", []):
                rows.append(
                    {
                        "location": location.upper(),
                        "station_id": station,
                        "date": item.get("date", "")[:10],
                        "datatype": item.get("datatype"),
                        "value": item.get("value"),
                        "unit": "F",
                        "source": "noaa_cdo",
                        "received_ts": datetime.now(timezone.utc),
                    }
                )
    finally:
        await client.close()

    out_dir = settings.data_dir / "processed" / "external" / "noaa_daily_observations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"location={location.upper()}-{start}-{end}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    console.print(f"Wrote {len(rows)} NOAA observation rows to {out_path}")


@app.command("collect-fred")
def collect_fred(
    series: str = typer.Option(...),
    start: str | None = None,
    end: str | None = None,
) -> None:
    asyncio.run(_collect_fred(series, start, end))


async def _collect_fred(series: str, start: str | None, end: str | None) -> None:
    client = FREDClient(settings.fred_api_key)
    try:
        payload = await client.get_observations(series, start=start, end=end)
    finally:
        await client.close()
    path = _write_json(
        settings.data_dir
        / "raw"
        / "external"
        / "fred"
        / f"series={series}-{_now_slug()}.json",
        payload,
    )
    console.print(f"Wrote FRED observations to {path}")


@app.command("collect-bls")
def collect_bls(
    series: str = typer.Option(...),
    start_year: int = typer.Option(...),
    end_year: int = typer.Option(...),
) -> None:
    asyncio.run(_collect_bls(series, start_year, end_year))


async def _collect_bls(series: str, start_year: int, end_year: int) -> None:
    client = BLSClient()
    try:
        payload = await client.get_timeseries(series, start_year, end_year)
    finally:
        await client.close()
    path = _write_json(
        settings.data_dir
        / "raw"
        / "external"
        / "bls"
        / f"series={series}-{_now_slug()}.json",
        payload,
    )
    console.print(f"Wrote BLS timeseries to {path}")


@app.command("parse-contracts")
def parse_contracts(series: str = "KXHIGHNY", apply_overrides: bool = False) -> None:
    asyncio.run(_parse_contracts(series, apply_overrides=apply_overrides))


async def _parse_contracts(series: str, apply_overrides: bool = False) -> None:
    markets = await _fetch_markets(series=series, status="all", limit=1000)
    overrides = _load_contract_overrides() if apply_overrides else None
    specs = parse_weather_contracts(markets, overrides=overrides)
    market_by_ticker = {market.get("ticker"): market for market in markets}
    rows = []
    for spec in specs:
        row = spec.to_row()
        market = market_by_ticker.get(spec.market_ticker, {})
        row.update(
            {
                "title": market.get("title"),
                "status": market.get("status"),
                "event_ticker": market.get("event_ticker"),
                "series_ticker": market.get("series_ticker"),
                "close_time": market.get("close_time"),
                "expiration_time": market.get("expiration_time"),
                "volume": market.get("volume"),
                "open_interest": market.get("open_interest"),
            }
        )
        rows.append(row)
    out_dir = settings.data_dir / "processed" / "contracts" / "weather_contract_specs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"series={series}-{_now_slug()}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    report_path = _write_contract_failure_report(series, markets, rows)
    parsed = sum(1 for row in rows if row.get("parse_status") == "parsed")
    console.print(f"Wrote {len(rows)} weather contract specs to {out_path}")
    console.print(
        f"Parsed successfully: {parsed}; failed: {len(rows) - parsed}; report: {report_path}"
    )


@app.command("build-labels")
def build_labels(series: str = "KXHIGHNY") -> None:
    asyncio.run(_build_labels(series))


async def _build_labels(series: str) -> None:
    markets = await _fetch_markets(series=series, status="all", limit=1000)
    rows = build_market_labels(markets)
    out_dir = settings.data_dir / "processed" / "labels" / "market_outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"series={series}-{_now_slug()}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    console.print(f"Wrote {len(rows)} labels to {out_path}")


@app.command("build-dataset")
def build_dataset(
    name: str = typer.Option(...),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    universe: str = "weather",
    require_labels: bool = typer.Option(
        False,
        "--require-labels",
        help="Build a supervised training dataset by excluding unresolved rows.",
    ),
    allow_unresolved_labels: bool = typer.Option(
        False,
        "--allow-unresolved-labels",
        help="Build a live/inference dataset where label may be null.",
    ),
) -> None:
    if universe != "weather":
        raise typer.BadParameter("Only the weather universe is implemented for Part 2.")
    if require_labels and allow_unresolved_labels:
        raise typer.BadParameter(
            "Use either --require-labels or --allow-unresolved-labels, not both."
        )

    base = settings.data_dir / "processed"
    contracts = _read_parquet_dir(base / "contracts" / "weather_contract_specs")
    forecasts = _read_parquet_dir(base / "external" / "nws_hourly_forecasts")
    if contracts is None:
        raise typer.BadParameter(
            "No weather contract specs found. Run parse-contracts first."
        )
    if forecasts is None:
        raise typer.BadParameter(
            "No NWS forecasts found. Run collect-nws-forecast first."
        )
    if "market_ticker" in contracts.columns:
        contracts = contracts.unique(subset=["market_ticker"], keep="last")
    if "parse_status" in contracts.columns:
        contracts = contracts.filter(pl.col("parse_status") == "parsed")
    if "contract_date" in contracts.columns:
        contracts = contracts.with_columns(pl.col("contract_date").cast(pl.Date))
        contracts = contracts.filter(
            (pl.col("contract_date") >= pl.lit(start).str.strptime(pl.Date, "%Y-%m-%d"))
            & (pl.col("contract_date") <= pl.lit(end).str.strptime(pl.Date, "%Y-%m-%d"))
        )

    book_features = _read_parquet_dir(base / "book_features")
    if book_features is None:
        console.print(
            "No Part 1 book_features found; bootstrapping live snapshot features."
        )
        book_features = asyncio.run(_bootstrap_market_features(contracts))
        out_dir = base / "book_features"
        out_dir.mkdir(parents=True, exist_ok=True)
        book_features.write_parquet(out_dir / f"bootstrap-{_now_slug()}.parquet")
    book_features = _normalize_book_feature_columns(book_features)
    if (
        "market_ticker" in book_features.columns
        and "market_ticker" in contracts.columns
    ):
        book_features = book_features.filter(
            pl.col("market_ticker").is_in(contracts["market_ticker"])
        )

    labels = _read_parquet_dir(base / "labels" / "market_outcomes")
    if labels is not None and "market_ticker" in labels.columns:
        labels = labels.unique(subset=["market_ticker"], keep="last")
    observations = _read_parquet_dir(base / "external" / "noaa_daily_observations")

    from eventmm.datasets.weather_dataset import build_weather_dataset

    out_path = build_weather_dataset(
        name=name,
        start=start,
        end=end,
        data_dir=settings.data_dir,
        market_features=book_features,
        weather_forecasts=forecasts,
        contract_specs=contracts,
        labels=labels,
        observations=observations,
        require_labels=require_labels,
        source_paths={
            "contract_specs": _parquet_paths(
                base / "contracts" / "weather_contract_specs"
            ),
            "book_features": _parquet_paths(base / "book_features"),
            "nws_forecasts": _parquet_paths(base / "external" / "nws_hourly_forecasts"),
            "noaa_observations": _parquet_paths(
                base / "external" / "noaa_daily_observations"
            ),
            "labels": _parquet_paths(base / "labels" / "market_outcomes"),
        },
    )
    console.print(f"Wrote dataset to {out_path}")
    if require_labels:
        console.print("Dataset mode: training/resolved-only labels.")
    elif allow_unresolved_labels:
        console.print("Dataset mode: live inference; unresolved labels allowed.")


@app.command("validate-dataset")
def validate_dataset(
    name: str = typer.Option(...),
    require_resolved: bool = True,
) -> None:
    df = pl.read_parquet(
        str(settings.data_dir / "processed" / "datasets" / name / "*.parquet")
    )
    stats = weather_validation_summary(df)
    error = None
    try:
        stats = validate_weather_dataset(df, require_resolved=require_resolved)
    except DatasetValidationError as exc:
        error = str(exc)
        report_path = _write_validation_report(name, df, stats, error)
        _write_part2_report(name, stats)
        _registry().update_metadata(
            name,
            {
                "validation_status": "failed",
                "validation_error": error,
                "validation_stats": stats,
            },
        )
        console.print(f"Dataset {name} failed validation: {error}")
        console.print(f"Wrote validation report to {report_path}")
        raise typer.Exit(1) from exc
    report_path = _write_validation_report(name, df, stats, None)
    _write_part2_report(name, stats)
    _registry().update_metadata(
        name,
        {
            "validation_status": "passed",
            "validation_error": None,
            "validation_stats": stats,
        },
    )
    console.print(f"Dataset {name} passed validation. Rows: {stats['rows']}")
    console.print(f"Wrote validation report to {report_path}")


@app.command("add-baseline-features")
def add_baseline_features(dataset: str = typer.Option(...)) -> None:
    in_dir = settings.data_dir / "processed" / "datasets" / dataset
    df = pl.read_parquet(str(in_dir / "*.parquet"))
    out = add_weather_baseline_features(df)
    out_dir = settings.data_dir / "processed" / "datasets" / f"{dataset}_features"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.parquet"
    out.write_parquet(out_path)
    write_dataset_manifest(
        out_dir,
        dataset_name=f"{dataset}_features",
        source_paths={"base_dataset": _parquet_paths(in_dir)},
        build_config={
            "derived_by": "add_weather_baseline_features",
            "base_dataset": dataset,
        },
    )
    console.print(f"Wrote baseline feature dataset to {out_path}")


@datasets_app.command("list")
def list_datasets() -> None:
    registry = _registry()
    for name in registry.list_datasets():
        console.print(name)


@datasets_app.command("describe")
def describe_dataset(name: str) -> None:
    metadata = _registry().describe(name)
    table = Table(title=f"Dataset: {name}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Created", str(metadata.get("created_ts", "")))
    table.add_row("Rows", str(metadata.get("row_counts", {}).get("dataset", "")))
    table.add_row("Markets", str(metadata.get("row_counts", {}).get("markets", "")))
    table.add_row("Labels", str(metadata.get("row_counts", {}).get("labels", "")))
    table.add_row("Date range", f"{metadata.get('start')} to {metadata.get('end')}")
    table.add_row("Dataset hash", str(metadata.get("dataset_hash", ""))[:16])
    table.add_row("Validation", str(metadata.get("validation_status", "")))
    table.add_row("Feature tables", ", ".join(metadata.get("feature_tables", [])))
    table.add_row("Feature columns", str(len(metadata.get("feature_columns", []))))
    table.add_row("Label table", str(metadata.get("label_table", "")))
    table.add_row("Sources", ", ".join(sorted(metadata.get("sources", {}))))
    table.add_row("Missingness", str(metadata.get("missingness", {})))
    console.print(table)


@datasets_app.command("feature-coverage")
def dataset_feature_coverage(
    dataset: str = typer.Option(...),
    label_col: str = "label",
) -> None:
    df = pl.read_parquet(str(_model_dataset_dir() / dataset / "*.parquet"))
    column_coverage = compute_column_coverage(df)
    feature_coverage = compute_feature_set_coverage(
        df, FEATURE_SETS, label_col=label_col
    )

    console.print(f"Dataset: {dataset}")
    console.print(f"Rows: {len(df)}")

    table = Table(title="Feature Coverage")
    table.add_column("Column")
    table.add_column("Coverage", justify="right")
    table.add_column("Non-null", justify="right")
    interesting = sorted(
        {
            label_col,
            "market_mid",
            "market_microprice",
            "market_spread",
            "market_depth_imbalance",
            "forecast_temperature",
            "forecast_minus_threshold",
            "observed_temperature",
            "time_to_expiry_hours",
        }
    )
    for row in column_coverage.filter(pl.col("column").is_in(interesting)).to_dicts():
        table.add_row(
            row["column"],
            f"{row['coverage_pct']:.1f}%",
            str(row["non_null"]),
        )
    console.print(table)

    set_table = Table(title="Usable Rows by Feature Set")
    set_table.add_column("Feature Set")
    set_table.add_column("Usable Rows", justify="right")
    set_table.add_column("Row Loss Columns")
    set_table.add_column("Missing Columns")
    for row in feature_coverage.to_dicts():
        set_table.add_row(
            row["feature_set"],
            str(row["usable_rows"]),
            row["row_loss_columns"],
            row["missing_columns"],
        )
    console.print(set_table)


@datasets_app.command("verify-manifest")
def verify_manifest(dataset: str = typer.Option(...)) -> None:
    path = _model_dataset_dir() / dataset / "manifest.json"
    if not path.exists():
        raise typer.BadParameter(f"No manifest found for {dataset}.")
    errors = verify_dataset_manifest(path)
    if errors:
        for error in errors:
            console.print(error)
        raise typer.Exit(1)
    console.print(f"Manifest verified: {path}")


@collector_app.command("health")
def collector_health(
    series: str = "KXHIGHNY",
    since: str = "24h",
) -> None:
    health = build_collector_health(settings.data_dir, series=series, since=since)
    table = Table(title=f"Collector Health: {series} since {since}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in health.as_dict().items():
        if isinstance(value, float):
            display = f"{value:.1f}%"
        else:
            display = "" if value is None else str(value)
        table.add_row(key, display)
    console.print(table)


@collector_app.command("weather-coverage")
def collector_weather_coverage(
    dataset: str | None = "weather_nyc_main_v1",
) -> None:
    coverage = build_weather_coverage(settings.data_dir, dataset=dataset)
    table = Table(title="Weather Data Coverage")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in coverage.as_dict().items():
        if isinstance(value, float):
            display = f"{value:.1f}%"
        else:
            display = "" if value is None else str(value)
        table.add_row(key, display)
    console.print(table)


@collector_app.command("freshness")
def collector_freshness(
    series: str = "KXHIGHNY",
    max_age_minutes: float = 30.0,
) -> None:
    freshness = check_collector_freshness(
        settings.data_dir, series=series, max_age_minutes=max_age_minutes
    )
    console.print(freshness)
    if not freshness.healthy:
        raise typer.Exit(1)


@orderbooks_app.command("audit")
def orderbooks_audit(
    series: str = "KXHIGHNY",
    since: str = "24h",
) -> None:
    audit = build_orderbook_audit(settings.data_dir, series=series, since=since)
    table = Table(title=f"Order-book Audit: {series} since {since}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    summary = audit.as_dict()
    top_markets = summary.pop("top_markets")
    for key, value in summary.items():
        table.add_row(key, "" if value is None else str(value))
    console.print(table)

    if top_markets:
        top_table = Table(title="Markets with Most Snapshots")
        top_table.add_column("Market")
        top_table.add_column("Snapshots", justify="right")
        for row in top_markets:
            top_table.add_row(str(row["market_ticker"]), str(row["snapshots"]))
        console.print(top_table)


@models_app.command("inspect-dataset")
def inspect_modeling_dataset(
    dataset: str = "weather_nyc_main_v1_features",
    feature_set: str = "weather_market",
) -> None:
    feature_cols = FEATURE_SETS[feature_set]
    loaded = load_modeling_dataset(
        dataset,
        feature_cols=[col for col in feature_cols],
        data_dir=_model_dataset_dir(),
    )
    table = Table(title=f"Modeling dataset: {dataset}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Rows after drop-null", str(len(loaded.y)))
    table.add_row("Features", ", ".join(loaded.feature_names))
    table.add_row("Positive labels", str(int(loaded.y.sum())))
    console.print(table)


@models_app.command("evaluate-baselines")
def evaluate_baselines(
    dataset: str = "weather_nyc_main_v1_features",
    feature_set: str = "market_only",
) -> None:
    df = pl.read_parquet(str(_model_dataset_dir() / dataset / "*.parquet"))
    feature_cols = [col for col in FEATURE_SETS[feature_set] if col in df.columns]
    usable_rows = (
        df.drop_nulls(feature_cols + ["label"]).height if "label" in df.columns else 0
    )
    rows = []
    if {"label", "market_mid"}.issubset(df.columns):
        scored = df.drop_nulls(["label", "market_mid"])
        if len(scored) > 0:
            rows.append(
                {
                    "model": "market_midpoint",
                    **evaluate_probabilities(
                        scored["label"], market_midpoint_probability(scored)
                    ),
                }
            )
    if {"label", "market_microprice"}.issubset(df.columns):
        scored = df.drop_nulls(["label", "market_microprice"])
        if len(scored) > 0:
            rows.append(
                {
                    "model": "microprice",
                    **evaluate_probabilities(
                        scored["label"], microprice_probability(scored)
                    ),
                }
            )
    forecast_signal_col = (
        "forecast_event_indicator"
        if "forecast_event_indicator" in df.columns
        else "forecast_above_threshold"
    )
    if {"label", forecast_signal_col}.issubset(df.columns):
        scored = df.drop_nulls(["label", forecast_signal_col])
        if len(scored) > 0:
            rows.append(
                {
                    "model": "forecast_threshold",
                    **evaluate_probabilities(
                        scored["label"], forecast_threshold_probability(scored)
                    ),
                }
            )

    metrics = pl.DataFrame(rows) if rows else pl.DataFrame()
    out_path = Path("artifacts") / "metrics" / f"{dataset}_baselines.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metrics.write_parquet(out_path)
    console.print(metrics)
    console.print(f"Feature set {feature_set} usable rows: {usable_rows}")
    console.print(f"Wrote baseline metrics to {out_path}")


@models_app.command("train-logistic")
def train_logistic(
    dataset: str = "weather_nyc_main_v1_features",
    feature_set: str = "weather_market",
    run_name: str = "weather_logistic_main_v1",
    model_id: str | None = None,
    min_rows: int = 30,
) -> None:
    if model_id:
        run_name = model_id
    feature_cols = FEATURE_SETS[feature_set]
    loaded = load_modeling_dataset(
        dataset,
        feature_cols=feature_cols,
        data_dir=_model_dataset_dir(),
    )
    if len(loaded.y) < min_rows:
        raise typer.BadParameter(
            f"Feature set {feature_set} has only {len(loaded.y)} usable rows. "
            f"Minimum required is {min_rows}. Try --feature-set market_only or collect more data."
        )
    if len(set(loaded.y.to_list())) < 2:
        raise typer.BadParameter(
            f"Feature set {feature_set} has only one label class after filtering. "
            "Collect more settled data before training."
        )

    model = make_logistic_regression_model(run_name).fit(
        loaded.X.to_pandas(),
        loaded.y.to_pandas(),
    )
    p_model = model.predict_proba(loaded.X.to_pandas())
    metrics = evaluate_probabilities(loaded.y, p_model)
    predictions = add_edge_columns(
        loaded.metadata.with_columns(pl.Series("p_model", p_model))
    )

    model_path = Path("artifacts") / "models" / f"{run_name}.joblib"
    pred_path = Path("artifacts") / "predictions" / f"{run_name}.parquet"
    report_path = Path("artifacts") / "reports" / f"{run_name}.md"
    calibration_path = Path("artifacts") / "reports" / f"{run_name}_calibration.md"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(model_path)
    predictions.write_parquet(pred_path)
    write_model_report(report_path, metrics)
    write_calibration_report(calibration_path, calibration_table(loaded.y, p_model))
    registry_path = ModelRegistry().write_run(
        run_name,
        {
            "dataset": dataset,
            "feature_set": feature_set,
            "feature_columns": feature_cols,
            "metrics": metrics,
            "model_path": str(model_path),
            "prediction_path": str(pred_path),
        },
    )
    console.print(metrics)
    console.print(f"Wrote model to {model_path}")
    console.print(f"Wrote model registry entry to {registry_path}")


@models_app.command("walk-forward")
def walk_forward_modeling(
    dataset: str = "weather_nyc_main_v1_features",
    feature_set: str = "weather_market",
    min_train_dates: int = 3,
) -> None:
    df = pl.read_parquet(str(_model_dataset_dir() / dataset / "*.parquet"))
    results = evaluate_walk_forward(
        df,
        feature_cols=FEATURE_SETS[feature_set],
        min_train_dates=min_train_dates,
    )
    out_path = Path("artifacts") / "metrics" / f"{dataset}_walk_forward.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.write_parquet(out_path)
    console.print(results)
    console.print(f"Wrote walk-forward metrics to {out_path}")


@backtest_app.command("inspect-data")
def backtest_inspect_data(dataset: str = "weather_nyc_main_v1_features") -> None:
    df = load_backtest_dataset(dataset, data_dir=_model_dataset_dir())
    summary = summarize_backtest_data(df)
    table = Table(title=f"Backtest data: {dataset}")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in summary.items():
        table.add_row(key, str(value))
    console.print(table)


@backtest_app.command("run")
def backtest_run(
    config: Path = Path("configs/backtest_weather_threshold.yaml"),
) -> None:
    cfg = yaml.safe_load(config.read_text())
    out_dir = run_threshold_backtest(cfg, data_dir=_model_dataset_dir())
    console.print(f"Wrote backtest artifacts to {out_dir}")


@research_app.command("partitions")
def research_partitions(
    dataset: str = "weather_nyc_main_v1_features",
    bucket_every: str = "1m",
) -> None:
    df = pl.read_parquet(str(_model_dataset_dir() / dataset / "*.parquet"))
    features = build_partition_features(df, bucket_every=bucket_every)
    violations = build_monotonicity_violations(df, bucket_every=bucket_every)
    out_dir = Path("artifacts") / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    features.write_parquet(out_dir / f"{dataset}_partition_features.parquet")
    violations.write_parquet(out_dir / f"{dataset}_monotonicity_violations.parquet")
    console.print(features)
    console.print(f"Monotonicity violations: {len(violations)}")


@research_app.command("simulate-baskets")
def research_simulate_baskets(
    dataset: str = "weather_nyc_main_v1_features",
    bucket_every: str = "1m",
    mode: str = "all_or_none",
    quantity: int = 1,
) -> None:
    mode = mode.replace("-", "_")
    if mode not in {"all_or_none", "partial"}:
        raise typer.BadParameter("Mode must be all-or-none or partial.")
    df = pl.read_parquet(str(_model_dataset_dir() / dataset / "*.parquet"))
    bucketed = (
        df.with_columns(
            pl.col("as_of_ts")
            .cast(pl.Datetime)
            .dt.truncate(bucket_every)
            .alias("quote_bucket")
        )
        .sort("as_of_ts")
        .unique(["event_ticker", "quote_bucket", "market_ticker"], keep="last")
    )
    rows = []
    fill_rows: list[dict[str, Any]] = []
    for _, group in bucketed.group_by(
        ["event_ticker", "quote_bucket"], maintain_order=True
    ):
        if group["market_ticker"].n_unique() != 6:
            continue
        for side in ("yes", "no"):
            result = simulate_partition_basket(
                group, side=side, mode=mode, quantity=quantity
            )
            row = asdict(result)
            row.pop("fills")
            rows.append(row)
            fill_rows.extend(
                {
                    "event_ticker": result.event_ticker,
                    "quote_bucket": result.quote_bucket,
                    "basket_side": side,
                    "simulation_mode": mode,
                    **fill.to_row(),
                }
                for fill in result.fills
            )
    output = pl.DataFrame(rows)
    out_path = (
        Path("artifacts") / "research" / f"{dataset}_basket_simulation_{mode}.parquet"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_parquet(out_path)
    pl.DataFrame(fill_rows).write_parquet(
        out_path.with_name(f"{out_path.stem}_fills.parquet")
    )
    console.print(output)


@research_app.command("forecast-revisions")
def research_forecast_revisions() -> None:
    source_dir = settings.data_dir / "processed" / "external" / "nws_hourly_forecasts"
    forecasts = _read_parquet_dir(source_dir)
    if forecasts is None:
        raise typer.BadParameter("No NWS forecast history found.")
    revisions = add_forecast_revision_features(forecasts)
    out_path = Path("artifacts") / "research" / "nws_forecast_revisions.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    revisions.write_parquet(out_path)
    console.print(f"Wrote {len(revisions)} forecast revision rows to {out_path}")

"""Standalone ingestion CLI: no modeling imports in the market-data process."""

import asyncio
import signal
import sys
from pathlib import Path

import typer

from eventmm.collector.archive import Archive
from eventmm.collector.service import CollectorConfig, MarketCollector
from eventmm.collector.supervisor import health, supervise
from eventmm.config.logging import configure_logging
from eventmm.config.settings import settings
from eventmm.kalshi.auth import KalshiAuth
from eventmm.kalshi.rate_limiter import TokenBucket
from eventmm.kalshi.rest_client import KalshiRestClient

app = typer.Typer(help="Durable read-only ingestion and worker supervision.")


def archive_path(worker: str) -> Path:
    return (
        settings.data_dir
        / "raw"
        / "collector"
        / settings.data_environment.value
        / f"{worker}.sqlite3"
    )


def run(coroutine):
    async def main():
        task = asyncio.current_task()
        assert task is not None
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await coroutine
        except asyncio.CancelledError:
            pass

    configure_logging(settings.log_level)
    asyncio.run(main())


@app.command("markets")
def markets(
    series: list[str] = typer.Option(
        ..., help="Repeat for each series; never silently truncates."
    ),
    requests_per_second: float = typer.Option(5, min=0.01),
    discovery_seconds: float = typer.Option(60, min=1),
    reconcile_seconds: float = typer.Option(120, min=1),
    max_markets: int = typer.Option(1000, min=1),
    private: bool = False,
):
    """Collect books, public trades and lifecycle; optionally private account events."""
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise typer.BadParameter(
            "WebSocket ingestion requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH"
        )
    auth = KalshiAuth(settings.kalshi_api_key_id, settings.kalshi_private_key_path)
    archive = Archive(archive_path("markets"))
    rest = KalshiRestClient(
        settings.rest_base_url, auth, TokenBucket(1, requests_per_second)
    )
    config = CollectorConfig(
        tuple(series),
        discovery_seconds=discovery_seconds,
        reconcile_seconds=reconcile_seconds,
        max_markets=max_markets,
        private=private,
    )
    try:
        run(MarketCollector(rest, auth, settings.ws_url, archive, config).run())
    finally:
        archive.close()


@app.command("weather")
def weather(
    source: str = typer.Option(..., help="nws or noaa; separate processes/archives."),
    location: list[str] = typer.Option(["NYC"]),
    interval: float = typer.Option(3600, min=60),
):
    from eventmm.collector.weather import run_weather
    from eventmm.collector.weather_sources import WEATHER_LOCATIONS

    if source not in {"nws", "noaa"}:
        raise typer.BadParameter("source must be nws or noaa")
    if any(loc.upper() not in WEATHER_LOCATIONS for loc in location):
        raise typer.BadParameter("Unknown weather location")
    if source == "noaa" and not settings.noaa_cdo_token:
        raise typer.BadParameter("NOAA_CDO_TOKEN is required for the NOAA worker")
    archive = Archive(archive_path(source))
    try:
        run(run_weather(source, location, archive, interval))
    finally:
        archive.close()


@app.command("supervise")
def supervise_command(
    series: list[str] = typer.Option(...),
    location: list[str] = typer.Option(["NYC"]),
    noaa: bool = False,
    private: bool = False,
    requests_per_second: float = typer.Option(5, min=0.01),
):
    """Supervise separate market, NWS and optional NOAA processes."""
    if noaa and not settings.noaa_cdo_token:
        raise typer.BadParameter("NOAA_CDO_TOKEN is required with --noaa")
    prefix = [sys.executable, "-m", "eventmm.collector_cli"]
    market_args = [arg for value in series for arg in ("--series", value)]
    market_args += ["--requests-per-second", str(requests_per_second)]
    if private:
        market_args += ["--private"]
    workers = [
        ("markets", [*prefix, "markets", *market_args], archive_path("markets"), 180)
    ]
    location_args = [arg for value in location for arg in ("--location", value)]
    for source in ["nws", "noaa"] if noaa else ["nws"]:
        workers.append(
            (
                source,
                [*prefix, "weather", "--source", source, *location_args],
                archive_path(source),
                4500,
            )
        )
    # Prevent two local supervisors from repeatedly restarting competing writers.
    owner = Archive(archive_path("supervisor"))
    try:
        run(supervise(workers))
    finally:
        owner.close()


@app.command("health")
def health_command(worker: str = "markets", max_age: float = 180):
    """Read persisted health without obtaining the writer lock."""
    import json

    try:
        typer.echo(json.dumps(health(archive_path(worker), max_age), indent=2))
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()

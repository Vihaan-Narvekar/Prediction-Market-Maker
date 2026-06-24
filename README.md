# eventmm-kalshi

Exchange-grade market data foundations for researching Kalshi binary event
market making. The project separates demo integration checks from production
public research data, historical backtesting data, and deterministic synthetic
test data.

## Core ideas

- Store raw market data first, then transform it.
- Use demo only for API/auth/WebSocket/order-lifecycle integration testing.
- Use production public data for live market-universe and order-book research.
- Use historical data for older trades, settled markets, replay, and calibration.
- Use synthetic data only for deterministic edge-case tests.
- Treat Kalshi Yes and No bids as the source of truth.
- Infer asks through the binary relationship:
  - Yes ask = `100 - best No bid`
  - No ask = `100 - best Yes bid`
- Refuse to silently accept sequence gaps during reconstruction.

## Quick start

```bash
uv sync
uv run pytest
uv run eventmm markets --status open --limit 10
uv run eventmm snapshot --market <MARKET_TICKER>
uv run eventmm inspect-book --market <MARKET_TICKER>
```

## Part 3 Modeling Status

Part 3 is implemented as a fair-value modeling framework, but the current
`weather_nyc_smoke_v1_features` dataset is still a pipeline-validation dataset.
It is expected to have too few fully populated rows for meaningful model claims
until NWS forecast snapshots are archived over time and more contracts settle.

Start forecast archiving with:

```bash
uv run eventmm archive-nws-forecast --locations NYC --iterations 1
```

Then inspect modeling readiness with:

```bash
uv run eventmm models inspect-dataset --dataset weather_nyc_smoke_v1_features
uv run eventmm models evaluate-baselines --dataset weather_nyc_smoke_v1_features
```

By default, `DATA_ENVIRONMENT=prod_public`, so unauthenticated REST market
commands use Kalshi's production public market-data API. Set
`DATA_ENVIRONMENT=demo` only when testing credentials or integration behavior.

Demo-environment data is intentionally excluded from market-quality and
trading-performance analysis because demo books may be sparse, artificial, or
non-representative.

## Project layout

```text
src/eventmm/
  config/       settings and structured logging
  kalshi/       auth, REST, WebSocket, rate limiting
  lob/          parsing, normalization, book reconstruction, features
  data/         Parquet and DuckDB helpers
  universe/     market pagination and filters
  monitoring/   data-quality counters and reports
```

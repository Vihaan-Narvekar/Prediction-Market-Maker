# eventmm-kalshi

Research, data collection, modeling, and event-driven backtesting tools for
Kalshi binary event markets. The current project is centered on New York daily
high-temperature markets and is designed for personal research—not unattended
live trading or large-scale production deployment.

## Current scope

Implemented functionality includes:

- Kalshi public REST market, order-book, trade, and historical-data clients.
- RSA authentication and an authenticated order-book WebSocket client.
- Binary YES/NO order-book parsing, reconstruction, validation, and features.
- Paginated market-universe loading and basic liquidity filters.
- NWS forecast, NOAA observation, FRED, and BLS data clients.
- A repeatable weather collector that archives raw responses and Parquet tables.
- Weather contract parsing for threshold and range contracts, plus overrides.
- Settlement-label generation and point-in-time weather/market dataset joins.
- Dataset registry, coverage, validation, and collector-health commands.
- Baseline fair-value metrics, logistic-regression training, and calibration reports.
- A simplified event-driven taker backtest with fills, fees, positions, and settlement.
- Research notebooks covering data collection through PnL diagnostics.

Not yet implemented are live order placement/cancellation, account
reconciliation, a realistic passive market-making simulator, depth-aware fills,
and production risk controls. Backtest results should be treated as research
outputs, not expected live performance.

## Data-use boundaries

- Store raw market data before transforming it.
- Use Kalshi demo only for authentication, API, WebSocket, and order-lifecycle
  integration tests. Demo liquidity is not research-representative.
- Use production public data for live market-universe and order-book research.
- Use historical data for replay, calibration, and settled-market analysis.
- Use synthetic data only for deterministic tests.
- Treat YES and NO bids as the source of truth. Infer asks with:
  - YES ask = `100 - best NO bid`
  - NO ask = `100 - best YES bid`
- Reject sequence gaps rather than silently reconstructing an invalid book.

## Installation

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --all-groups
cp .env.example .env
```

Runtime dependencies live in `[project.dependencies]`; notebooks, tests,
formatters, typing tools, and coverage support live in the `dev` dependency
group. A runtime-only environment can be installed with:

```bash
uv sync --no-dev --frozen
```

Do not commit `.env`, private keys, collected data, logs, or generated artifacts.

## Common commands

Inspect public markets and books:

```bash
uv run eventmm markets --status open --limit 10
uv run eventmm snapshot --market <MARKET_TICKER>
uv run eventmm inspect-book --market <MARKET_TICKER>
```

Run one weather collection cycle:

```bash
uv run eventmm run-weather-collector --locations NYC --series KXHIGHNY --iterations 1
uv run eventmm collector health --series KXHIGHNY --since 24h
uv run eventmm collector weather-coverage --dataset weather_nyc_main_v1
uv run eventmm orderbooks audit --series KXHIGHNY --since all
```

The long-running personal collector wrapper is:

```bash
./scripts/run_live_weather_collector.sh
```

It is a simple shell-loop service. Run it under a local supervisor if automatic
restart behavior is needed.

## Weather dataset workflow

The canonical local dataset is `weather_nyc_main_v1`; the derived modeling
dataset is `weather_nyc_main_v1_features`. Both depend on locally collected,
Git-ignored source data.

```bash
uv run eventmm parse-contracts --series KXHIGHNY --apply-overrides
uv run eventmm build-labels --series KXHIGHNY
uv run eventmm build-dataset \
  --name weather_nyc_main_v1 \
  --start 2026-06-25 \
  --end 2026-07-01 \
  --allow-unresolved-labels
uv run eventmm validate-dataset --name weather_nyc_main_v1 --no-require-resolved
uv run eventmm add-baseline-features --dataset weather_nyc_main_v1
```

Inspect coverage and modeling readiness:

```bash
uv run eventmm datasets list
uv run eventmm datasets describe weather_nyc_main_v1
uv run eventmm datasets feature-coverage --dataset weather_nyc_main_v1_features
uv run eventmm models inspect-dataset --dataset weather_nyc_main_v1_features
uv run eventmm models evaluate-baselines --dataset weather_nyc_main_v1_features
```

Train the current logistic prototype and run the simplified threshold backtest:

```bash
uv run eventmm models train-logistic \
  --dataset weather_nyc_main_v1_features \
  --feature-set weather-market
uv run eventmm backtest inspect-data --dataset weather_nyc_main_v1_features
uv run eventmm backtest run --config configs/backtest_weather_threshold.yaml
```

The current training command evaluates in-sample and the fill model is highly
simplified. Out-of-sample splitting and more conservative execution simulation
are the next research priorities.

## Quality checks

Run the local quality gate with:

```bash
make check
```

Individual commands are:

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
JUPYTER_CONFIG_DIR=/tmp/eventmm-jupyter uv run jupyter nbconvert --execute --to notebook --output-dir /tmp/eventmm-notebooks notebooks/*.ipynb
```

Pytest measures branch coverage for `src/eventmm` and fails below **40%**.
It prints missing lines to the terminal and writes `coverage.xml`. The initial
whole-package baseline is 43.89%; the threshold prevents a material regression
while remaining attainable for a personal research project whose CLI and
external-service orchestration are not yet integration-tested. Raise it as
collector, modeling, backtest, and CLI integration tests are added.

GitHub Actions runs lint, typing, tests with coverage, clean-checkout notebook
execution, and package building on pushes and pull requests.

## Docker

Build a runtime-only image with:

```bash
docker build -t eventmm-kalshi .
docker compose run --rm eventmm
```

The default container command lists public markets and exits. Local data,
artifacts, logs, environment files, and secret keys are excluded from the image
build context. Compose mounts local `data/`, `configs/`, and `secrets/` paths for
personal use; it is not a hardened live-trading deployment.

## Project layout

```text
src/eventmm/
  backtest/       replay events, strategies, fills, fees, portfolio, reports
  config/         environment settings and structured logging
  contracts/      weather parsing and settlement-label helpers
  data/           Parquet buffering and DuckDB helpers
  data_sources/   demo, production-public, historical, and synthetic profiles
  datasets/       joins, schemas, registry, validation, labels, and coverage
  external/       NWS, NOAA, FRED, and BLS clients
  kalshi/         authentication, REST, WebSocket, and rate limiting
  lob/            binary-book parsing, normalization, reconstruction, features
  modeling/       feature sets, models, evaluation, splits, and registry
  monitoring/     collector, book-quality, and weather-coverage reports
  pipelines/      operational weather collection workflow
  reports/        model and calibration report writers
  research/       derived research features and diagnostics
  signals/        fair-value and edge helpers
  universe/       market loading and filtering
configs/          collector, dataset, model, universe, and backtest configuration
notebooks/        numbered research workflow notebooks
reports/          checked-in research and validation summaries
tests/            unit and component tests
```

## Configuration and credentials

Settings are read from environment variables and `.env`. See `.env.example`.
Public production-market commands require no Kalshi credentials. NOAA collection
requires `NOAA_CDO_TOKEN`. Authenticated Kalshi integrations require
`KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PATH`.

Keep live credentials separate from demo credentials. Live order execution is
not currently implemented.

## Near-term roadmap

1. Make datasets immutable and record exact input manifests.
2. Add grouped temporal/walk-forward model evaluation.
3. Compute edge against executable YES/NO quotes after fees.
4. Add depth-limited fills, latency, position limits, and non-reusable liquidity.
5. Implement all-or-none partition-basket simulation.
6. Improve collector supervision, freshness alerts, and sequence-gap recovery.
7. Add paper-trading state and reconciliation before considering live orders.

## Next commit scope

The next commit should be one cohesive quality-baseline commit containing:

- Existing contract-aware weather features, strategy updates, research notebooks,
  configs, and supporting tests already present in the working tree.
- Notebook syntax/execution fixes.
- Source typing fixes and narrowly scoped third-party mypy configuration.
- Runtime/development dependency separation and the refreshed lockfile.
- Test coverage reporting with the 40% minimum and documented 43.89% baseline.
- GitHub Actions CI, `.dockerignore`, and runtime-only Docker installation.
- This expanded project documentation and the related research reports.

It should exclude local `.env`, credentials, `data/`, `artifacts/`, `logs/`,
caches, and generated notebook execution outputs. The deleted obsolete smoke
validation report belongs in the commit because the canonical main validation
report replaces it. A suitable message is:

```text
Establish quality baseline for weather research workflow
```

## License

See [LICENSE](LICENSE).

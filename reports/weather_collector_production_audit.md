# Weather Collector Production Audit

Audit date: 2026-07-03

## Executive Summary

The collector did write the production order-book and weather data. The empty/weak backtest result was not caused by missing collector output. It was caused by downstream consumers using stale validation datasets/configs. The production collector-backed dataset is now named `weather_nyc_main_v1`, and its feature dataset is `weather_nyc_main_v1_features`.

- `logs/weather_collector.log` records successful production writes through `2026-07-02T02:59Z`.
- `weather_nyc_live_v1` was last built on June 28 and only contains rows through `2026-06-28 20:03:52`.
- Backtest/model configs now point to `weather_nyc_main_v1_features`.
- The main dataset contains `4,410` rows and `2,157` usable `weather_market` modeling rows.
- A threshold backtest on the main feature dataset produced `1,709` fills across `23` markets.

## Collector Log Evidence

Source: `logs/weather_collector.log`

Summary parsed from the log:

| Event | Count | Logged Rows | Latest Write |
| --- | ---: | ---: | --- |
| collector runs | 369 | n/a | `2026-07-02T02:59:22Z` |
| market universe writes | 369 | n/a | `part-20260702T025927Z.parquet` |
| order-book feature writes | 369 | 4,404 | `collector-KXHIGHNY-20260702T025931Z.parquet` |
| NWS forecast writes | 369 | 57,564 | `location=NYC-20260702T025931Z.parquet` |
| NOAA observation writes | 367 | 5,028 | `location=NYC-2026-06-24-2026-07-01.parquet` |
| label writes | 367 | 151,938 | `series=KXHIGHNY-20260702T025947Z.parquet` |

There is one traceback at the end of the log. It happens after the final label write, when the wrapper script starts `eventmm collector health`. The interrupt occurs while importing SciPy/scikit-learn through the global CLI import chain. It does not invalidate the prior collector writes in that run.

## Current Production Data on Disk

| Source Table | Files | Rows | Time/Date Range |
| --- | ---: | ---: | --- |
| `data/processed/book_features` | 373 | 4,854 | `2026-06-23 23:19:53Z` to `2026-07-02 02:59:31Z` |
| `data/processed/external/nws_hourly_forecasts` | 377 | 58,812 | issue timestamps through `2026-07-02 02:59:31Z`; forecast dates through `2026-07-08` |
| `data/processed/external/noaa_daily_observations` | 10 | 186 | files through `location=NYC-2026-06-24-2026-07-01.parquet` |
| `data/processed/labels/market_outcomes` | 371 | 153,594 | latest file `series=KXHIGHNY-20260702T025947Z.parquet` |

Book-feature quality by source rows:

- Total book feature rows: `4,854`
- Rows with `market_mid`: `2,422`
- Unique markets represented: `462`
- Latest book feature row: `2026-07-02 02:59:31Z`

## Existing Dataset Resolution

Current registered datasets:

| Dataset | Rows | Markets | Label Rows | Status |
| --- | ---: | ---: | ---: | --- |
| `weather_nyc_main_v1` | 4,410 | 42 | 4,146 | canonical main production dataset |
| `weather_nyc_live_v1` | 2,544 | 42 | 2,094 | usable but stale |

`weather_nyc_live_v1_features` currently ends at:

- `as_of_ts`: `2026-06-28 20:03:52`
- `contract_date`: `2026-06-29`

That means it excludes later collector output from June 29, June 30, and July 2.

The previous validation-only dataset has been removed from the project. The backtester/modeling defaults now route to `weather_nyc_main_v1_features`.

## Main Dataset Rebuild

Command used:

```bash
uv run eventmm build-dataset --name weather_nyc_main_v1 --start 2026-06-25 --end 2026-07-01 --allow-unresolved-labels
uv run eventmm add-baseline-features --dataset weather_nyc_main_v1
```

Resulting feature dataset: `weather_nyc_main_v1_features`

| Metric | Value |
| --- | ---: |
| rows | 4,410 |
| markets | 42 |
| resolved markets | 36 |
| timestamp start | `2026-06-25 20:52:42` |
| timestamp end | `2026-07-02 02:59:31` |
| book rows | 2,409 |
| forecast rows | 4,410 |
| label rows | 4,146 |
| `weather_market` usable modeling rows | 2,157 |
| positive labels in modeling rows | 457 |

Feature coverage:

| Column | Coverage | Non-null |
| --- | ---: | ---: |
| `forecast_temperature` | 100.0% | 4,410 |
| `forecast_minus_threshold` | 100.0% | 4,410 |
| `time_to_expiry_hours` | 100.0% | 4,410 |
| `market_depth_imbalance` | 100.0% | 4,410 |
| `label` | 94.0% | 4,146 |
| `observed_temperature` | 57.3% | 2,526 |
| `market_mid` | 54.6% | 2,409 |
| `market_microprice` | 54.6% | 2,409 |
| `market_spread` | 54.6% | 2,409 |

This confirms the collector output can produce usable production modeling rows when the dataset is rebuilt from the correct source range.

## Backtest Result

Backtest run: `weather_threshold_main_v1`

Dataset: `weather_nyc_main_v1_features`

| Metric | Value |
| --- | ---: |
| number of markets | 23 |
| orders | 1,709 |
| fills | 1,709 |
| fill rate | 1.0 |
| average fill price | 39.19 |
| gross PnL | 7,893.0 |
| fees | 170.9 |
| net PnL | 7,722.1 |
| PnL per contract | 4.52 |
| win rate | 0.696 |

This confirms the backtester has usable rows when pointed at the main production feature dataset.

## Issues Found

1. Production data exists, and `weather_nyc_main_v1` is now the canonical dataset name.
2. Older stale datasets may still exist for comparison, but normal commands should use `weather_nyc_main_v1_features`.
3. `validate-dataset` treats unresolved labels as a failure even for live/inference datasets, while `build-dataset --allow-unresolved-labels` intentionally allows them. The command/reporting semantics should distinguish supervised training validation from live inference validation.
4. The CLI imports modeling/scikit-learn at top level. This made `eventmm collector health` vulnerable to a SciPy import interrupt, even though collector health should not need modeling dependencies.
5. Collector health with `--since 24h` can report zero orderbooks/forecasts if the collector has not run in the last 24 hours, even when historical production data exists. For project status, use both `--since 24h` freshness and `--since all` inventory views.

## Recommended Fix Plan

1. Promote a production dataset naming convention, for example `weather_nyc_live_v2` or date-stamped names like `weather_nyc_prod_20260702`.
2. Rebuild the production dataset after collector runs:

```bash
uv run eventmm build-dataset --name weather_nyc_live_v2 --start 2026-06-25 --end 2026-07-01 --allow-unresolved-labels
uv run eventmm add-baseline-features --dataset weather_nyc_live_v2
```

3. Keep backtest/model configs pointed at `weather_nyc_main_v1_features`.
4. Add a separate config for supervised-only training/backtesting that either requires labels or filters unresolved rows explicitly.
5. Split CLI imports so collector and monitoring commands do not import scikit-learn/modeling dependencies.
6. Add a freshness report that displays both latest timestamps and all-time row counts for market, book, forecast, NOAA, and label tables.

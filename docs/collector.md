# Supervised data collection

This service collects data only. It cannot submit orders and never certifies the
account reconciliation required by the trading gate. Optional private streams are
archived for research and recovery; enabling them does not enable trading.

## Run

Set `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PATH` in the environment or `.env`.
Public WebSocket channels still require a signed connection. Keep credentials out
of the archive. `DATA_ENVIRONMENT` selects production or demo, as with the existing
CLI; archives are separated by that environment.

```sh
# Market ingestion, plus a separately supervised NWS process:
uv run python -m eventmm.collector_cli supervise --series KXHIGHNY --location NYC

# Add an independent NOAA process (requires NOAA_CDO_TOKEN):
uv run python -m eventmm.collector_cli supervise --series KXHIGHNY --location NYC --noaa

# Repeat --series for additional series. Private events are opt-in:
uv run python -m eventmm.collector_cli markets --series KXHIGHNY --private

# Same command group is available under the main CLI:
uv run eventmm ingest health --worker markets --max-age 180

# Weather workers can also run individually:
uv run python -m eventmm.collector_cli weather --source nws --location NYC --interval 3600
uv run python -m eventmm.collector_cli health --worker nws --max-age 4500
```

The `eventmm-collect` entry point is an alias for the lightweight module command.
`scripts/run_supervised_collector.sh` defaults to NYC/KXHIGHNY and accepts the same
supervisor options. The older `run_live_weather_collector.sh` remains a legacy
polling workflow; do not launch it alongside this collector against the same data.

For host-restart persistence:

```sh
docker compose -f docker-compose.collector.yml up -d --build
docker compose -f docker-compose.collector.yml logs -f
docker compose -f docker-compose.collector.yml down
```

The sample mounts `secrets/kalshi_private_key.pem` read-only; adjust that filename
and the selected series/location in the compose file for your deployment. Docker
restarts the supervisor after process/host failure; the supervisor independently
restarts failed or stale child workers with a 2–60 second exponential delay.
SIGTERM/SIGINT cancel workers gracefully, then terminate/reap children, with a kill
fallback after 20 seconds. Logs rotate in Docker. The supervisor and each archive
hold exclusive writer locks, so duplicate local invocations fail rather than
silently creating competing collectors.

## What is persisted

`data/raw/collector/<data_environment>/markets.sqlite3` contains:

| Table | Contents |
| --- | --- |
| `records` | Append-only raw WS frames, raw REST response bodies with URLs/status, complete market metadata, discovery results, connection boundaries, reconciliation results and errors |
| `trades` | Public trades deduplicated by exchange `trade_id`; fixed-point values remain decimal strings |
| `checkpoints` | Completed trade-window watermarks, known/retired markets, health |

Each record has a durable increasing ID, UTC receipt nanoseconds, monotonic receipt
nanoseconds, kind and WebSocket session ID. Frames are committed **before** JSON
parsing and state validation; malformed, duplicate and rejected frames remain in
the raw archive. A session is a replay boundary; never carry its book through a
new session without a snapshot. `trade` is the public channel; `fill` is the
private account channel and is not a replacement for public trade data.

SQLite uses WAL and `synchronous=FULL`; successful writes are committed, and local
writer locking prevents concurrent service writers. Each commit applies
backpressure to the bounded WS receive queue. A storage failure is fatal, not a
reconnect-and-drop path. No retention policy deletes raw records. Use a local
persistent filesystem with working SQLite locks/fsync; do not put the live WAL on
an object-store or network mount. Back up with SQLite's online backup API, or stop
the service before copying the database. Copying only an active `.sqlite3` file
without its WAL is unsafe.

The database is directly queryable while ingestion is active:

```sql
SELECT kind, COUNT(*) FROM records GROUP BY kind;
SELECT id, received_ns, session, CAST(payload AS TEXT)
FROM records WHERE kind = 'websocket' ORDER BY id LIMIT 20;
SELECT COUNT(*) FROM trades;
SELECT CAST(value AS TEXT) FROM checkpoints WHERE key = 'health';
```

Raw bytes retain API decimal dollar/quantity strings. Existing normalized book
classes still express **decimal cents** internally; the collector introduces no
binary floating-point financial conversions. UTC/monotonic timestamps and rate
intervals use ordinary time types.

## Discovery, recovery and budgets

- Discovery scans every page of every explicitly selected series every 60 seconds.
  A failed or incomplete scan does not remove existing subscriptions. Repeated
  cursors, page-budget exhaustion and exceeding the configurable market cap are
  explicit failures, not successful partial results.
- New and retired markets change the subscription universe through a controlled
  reconnect. All enrolled markets receive fresh sequenced WS snapshots. This
  records a real collection boundary and may miss depth changes during enrollment.
- The market process runs discovery, stream consumption, reconciliation and health
  independently. NWS and NOAA have separate processes, archives and rate budgets.
- Reconciliation runs every 120 seconds. Public trades are recovered through all
  pages of a fixed `[min_ts, max_ts]` window, with a 60-second overlap and durable
  deduplication. A first enrollment starts one hour back; subsequent runs resume
  from the last **completed** window, including across restarts. The initial start
  is persisted before collection so failures do not advance it. Queries crossing
  the exchange historical cutoff are split between live and historical endpoints.
- Retired markets continue trade catch-up and REST metadata collection for 24 hours
  before removal. Global lifecycle messages remain archived. This window is a
  collection policy, not a guarantee of final settlement for all product types.
- Full REST books are archived and compared to the live book only when the WS
  epoch and sequence counters remain unchanged across the request. A mismatch
  invalidates the local baseline and requests a WS snapshot; concurrent updates
  are marked inconclusive. REST and WS are not an atomic exchange snapshot.
- An independent monitor refreshes quiet books after 30 seconds, even when other
  markets are active. A requested snapshot that does not arrive within 60 seconds
  fails the worker. Sequence gaps and protocol errors invalidate state and
  reconnect. The market collector uses a capped 2–60 second reconnect delay.
- Kalshi REST defaults to five **requests** per second in the collector, burst one;
  override `--requests-per-second` to fit the account and other clients. Discovery
  and reconciliation share that limiter. These units are local request budgets,
  not a claim about Kalshi's account-tier token costs. External workers default to
  one request per second per source. Every retry consumes the same budget.
- GETs retry transport failures and 408/429/500/502/503/504 only, at most four
  attempts within a 60-second overall deadline, with jitter and `Retry-After`
  support. Auth and other nonretryable errors fail immediately. Pagination has a
  10,000-page safety ceiling. No retry is made after a persistence error.

`health` checks the heartbeat, discovery, live connection/frame freshness and
reconciliation age. The supervisor recycles stale processes after their startup
grace. A small `valid_books` count is visible in health and snapshot recovery
handles missing baselines; a healthy collector is **not** a trading-ready signal.
The trading gate continues to deny new exposure while state/account reconciliation
is invalid. A future execution service must reconcile private account state before
allowing orders; this collector does not infer that REST and WS are synchronized.

## Weather outputs and current limits

Each weather worker also writes its complete HTTP responses to its own SQLite
archive before creating the existing JSON/Parquet outputs. NOAA follows result
count/offset pagination. Repeated downloads use unique filenames, preserving
observation revisions and forecast versions instead of overwriting them. Existing
`forecast_issue_ts` retains collection-time availability semantics for downstream
compatibility; `source_issue_ts` records the reported source timestamp separately.

NYC has configured GHCND station identifiers. The legacy non-NYC mappings use
airport codes and are rejected for NOAA until verified GHCND identifiers are
configured. NWS collection can use the existing city coordinates independently.
This change does not validate station-to-contract settlement mappings or repair
the existing daily forecast/label feature semantics identified in the audit.

There is no historical L2 backfill: public trades can recover a disconnect window,
but missing depth updates cannot be invented. Research must exclude invalid
intervals or replay from the next snapshot. The archive is not yet automatically
materialized into the existing feature datasets. Dataset materialization and
replay-quality reports are the next development step.

Archive growth and synchronous-commit throughput need measurement during the
initial production soak. No retention/compaction job is enabled; provision disk
space and use backups before expanding the universe. HTTP rate limits are per
process, so other programs sharing the same account/token consume additional
quota. This implementation has automated mock transport/recovery tests; a live
authenticated deployment still needs a monitored soak before relying on coverage.

## API references

- [Public trades](https://docs.kalshi.com/websockets/public-trades)
- [Orderbook snapshots, deltas and snapshot refresh](https://docs.kalshi.com/websockets/orderbook-updates)
- [Historical cutoffs and pagination](https://docs.kalshi.com/getting_started/historical_data)

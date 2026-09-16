# Data collection audit and development plan

Audit: September 15, 2026, US Eastern / September 16, 2026, UTC. Scope: the current local working tree, local Parquet/JSON data, DuckDB, registry, collector log, and process listing. This includes the recent uncommitted decimal and WebSocket work. No remote deployment was inspected. No collectors were started, source datasets rebuilt, or orders sent during this audit.

**Recommendation: prioritize continuous, replayable capture and repair weather/settlement semantics before further strategy selection.** There is enough data to develop plumbing and test hypotheses, but not enough reliable execution data to validate passive market making. More rows from the current pipeline would reproduce important defects.

The machine-readable measurements are in [data_collection_inventory_20260916.json](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/reports/data_collection_inventory_20260916.json). Counts were computed from actual files rather than copied from the older July reports. Historical source files include repeated polls and bootstrap attempts; row counts must not be interpreted as independent observations.

## 1. Current collection and data inventory

No `eventmm` or weather-collector process appeared in the local process listing. The last logged collector invocation is **2026-07-12 02:25:29 UTC**; the last book and NWS timestamps are **2026-07-12 02:25:32 UTC**, approximately **66 days before this audit**. This establishes local staleness, not the status of an uninspected remote host.

| Asset | Measured local state | Interpretation |
|---|---|---|
| Book feature files | 379 files; 4,926 rows; June 23–July 12 | Periodic REST-derived summaries, not a historical event stream |
| Observed capture days | 10 distinct UTC dates | The calendar span substantially overstates continuity |
| Book quality | 2,449 rows with both bid sides; 2,063 one-sided; 414 empty/error | Roughly half of all source rows have both sides; these categories do not establish collection availability |
| Midpoint coverage | 2,452 rows | Three older rows have midpoint without both current bid fields; legacy schema differences need normalization |
| Depth | Only 30 source rows have both YES bid and ask depth | All such rows are from July 12 |
| Errors | 74 stored feature errors, all HTTP 429 | Rate-limit losses are real, not just a hypothetical concern |
| Market breadth | 474 tickers appear in book features; only 72 have a nonempty book and 49 a midpoint | Many ticker rows are old-contract bootstrap attempts, not useful historical books |
| NWS | 383 files; 59,748 hourly forecast rows; NYC only | Repeated polls plus multiple forecast horizons dominate this count |
| Forecast novelty | 18 distinct source update timestamps and 56 distinct period payloads across 383 raw responses | Poll/version-file count is not the number of independent forecast releases |
| NOAA | 201 stored rows; 99 distinct station/date pairs; 33 dates across three NYC stations | Missing June 29–July 3; latest observed date July 8 |
| Labels | 156,078 rows, 522 unique markets; latest per-market records: 510 resolved, 12 unresolved | Repeated snapshots of mostly the same settlement results |
| Contract specs | 69,966 rows, 522 unique tickers | Repeated metadata is not equivalent to training examples |
| Raw exchange data | No local Kalshi raw book/delta/trade/private-event archive found | Past book changes cannot be replayed from this repository |
| DuckDB | No tables | Parquet is the actual local data store; there is no populated analytical warehouse behind it |

During active periods, the median per-market snapshot interval is **308 seconds**; p95 is **1,680 seconds**. Run-to-run gaps include **44.7 hours**, **27.8 hours**, and **238.7 hours**. These exclude the subsequent approximately 66-day stoppage. The shell wrapper sleeps five minutes after work finishes, so five minutes is not a guaranteed fixed sampling cadence.

### Existing analysis datasets

| Measurement | `weather_nyc_main_v1_features` | `weather_nyc_revision_v2_features` |
|---|---:|---:|
| Rows | 4,410 | 4,476 |
| Contract dates | 7 | 10 |
| Markets | 42 | 60 |
| Dates with stored resolved labels | 6 | 8 |
| Markets with stored resolved labels | 36 | 48 |
| Rows with midpoint | 2,409 | 2,438 |
| Rows with both top-level depths | 0 | 25 |
| Rows with both depths and a label | 0 | **0** |
| `weather_market` usable modeling rows | 2,157 | 2,413 |
| Usable modeling dates | 5 | 7 |
| Possible expanding-date test folds after three training dates | 2 | 4 |
| Latest captured row | July 2, 02:59 UTC | July 12, 02:20 UTC |

The newer dataset adds only **66 rows**, including just 60 July 12 captures. Its final collector batch of 12 rows at 02:25 was never incorporated. Its 25 two-sided depth rows cover unresolved contracts in the saved artifact. Updating labels may repair that join, but cannot create missing order-book history. The seven usable modeling dates are also highly uneven; one date contributes only four midpoint rows.

Model/backtest configuration files still select `weather_nyc_main_v1_features`. The older `weather_nyc_live_v1_features` cannot load the current `weather_market` feature set because it lacks `forecast_event_indicator`.

### Provenance is already broken in one source chain

The base `weather_nyc_revision_v2` manifest reports a hash mismatch for:

`data/processed/external/noaa_daily_observations/location=NYC-2026-07-04-2026-07-11.parquet`

The derived feature manifest passes because it checks its immediate base Parquet input, not the base dataset's transitive source history. Three older dataset directories have no manifest. The existing checks are useful, but a passing feature manifest is not proof of reproducible end-to-end lineage.

## 2. Deficiencies and why they matter

### P0: The capture service is neither continuous nor event based

[WeatherCollectorPipeline](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/pipelines/weather_collector.py:20) runs metadata, books, forecasts, NOAA, and labels sequentially. A slow/failing external source delays or aborts the whole cycle. [The shell wrapper](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/scripts/run_live_weather_collector.sh:1) has `set -euo pipefail`: an unhandled collector failure or a failing freshness command exits the loop. There is no deployed supervisor, restart policy, or durable checkpoint in this repository. Docker Compose runs a one-shot `markets` command, not a collector.

[Book collection](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/cli.py:258) fetches each book over REST, computes features, then discards the levels. It records one timestamp before the HTTP request, not exchange event time plus receive/persist timestamps. It omits raw responses, subscription/sequence information, full depth, and several book-quality fields already available from `compute_features`. A five-minute summary cannot measure queue depletion, cancellations, spread duration, quote lifetime, or adverse selection at execution horizons.

### P0: The new WebSocket code is a component, not an operating ingestion system

[The WebSocket client](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/kalshi/ws_client.py:18) and [StreamState](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/kalshi/stream_state.py:63) now handle books/private/lifecycle state and a trading gate. However:

- No collector command or pipeline instantiates the client; no durable writer consumes its messages.
- The supported channel set still lacks public `trade` and `ticker`; private `fill` is only this account's fills, not the market's trade tape.
- Subscribed tickers are fixed for a client instance. Lifecycle events do not enroll newly opened markets or manage daily rollover.
- No complete REST/private reconciliation service exists. The gate correctly waits for caller certification, but no application implements that workflow.
- The receive loop awaits the consumer directly. Persistence/model work in the handler can delay reception; backpressure is not measured or managed by an application queue.
- Freshness is based on time since a book message. Quiet-but-valid books and broken feeds need separate treatment. Conversely, traffic on unrelated channels can keep the socket busy while one market remains stale; there is no periodic per-market snapshot audit/recovery scheduler.
- Readiness is checked at submission time; there is no durable halt-transition stream, order transport, or policy to cancel already-resting orders after loss of trusted state.
- In-memory orders/fills/groups have no retention/checkpoint policy. Reconnection does not make the cache a complete account history.

These are integration gaps remaining after the recent improvements, not reasons to discard those improvements.

### P0: The daily-high forecasting target is assembled incorrectly

[The weather join](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/datasets/joins.py:43) filters all hourly forecast periods for a contract date, sorts by issue timestamp, and takes one final row. It does **not** aggregate the forecast into the contract's daily high. Multiple hours share an issue timestamp, so the selected hour is not a stable target definition.

Measured against the same forecast collections used in `weather_nyc_revision_v2`, **3,786 of 4,464 matched rows (84.8%) differ from the daily maximum hourly forecast**. The average shortfall across matched rows is **3.09°F**, with a maximum of **11°F**. This is a semantic discrepancy, not proof that the daily maximum forecast is a calibrated forecast of the official settlement reading.

The revision-analysis code does aggregate daily maxima, so model features and revision studies currently use inconsistent forecast definitions. Same-day forecasts need an additional distinction: the maximum of the remaining forecast hours is not the completed daily maximum. Observations-so-far must be incorporated only if available by the decision timestamp, or the dataset must explicitly restrict itself to a pre-day forecasting task.

### P0: Observation aggregation does not honor a settlement station

[Observation aggregation](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/datasets/joins.py:4) chooses the highest temperature across all stations for a location/date. It is not an exact settlement-station join. Every non-null observation in the newest dataset comes from `USW00014732`; every `settlement_station` is null. No label has a populated settlement-rule match.

The same cross-station maximum appears in [forecast-error construction](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/research/forecast_error_model.py:53). An existing test explicitly expects the hottest of two stations, so passing tests currently preserve this incorrect assumption for station-specific contracts. The correct station, source publication, local day, rounding, and threshold rules must come from archived exchange contract rules, not an inferred city mapping.

### P1: Discovery and historical coverage are incomplete

[The collector's `_fetch_markets`](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/cli.py:155) fetches only one page per status and ignores returned cursors. A paginating `MarketLoader` exists elsewhere but is unused here. Metadata, parsing, book discovery, and label collection make repeated discovery calls in the same cycle.

Current market responses are normalized, but [the persisted universe](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/cli.py:181) strips full rules, price ranges, market structure, response provenance, and collection timestamps. All persisted `series_ticker` values are null. Series/event identity should be joined from discovery context or parent endpoints rather than assumed to exist on every market response. The label extractor still looks for `settlement_timer`/`settled_time`; all saved `settlement_time` values are null, and current settlement metadata needs explicit mapping.

The REST client has historical cutoff/market/trade methods, but no complete backfill workflow, pagination/checkpoint orchestration, or candle ingestion. Kalshi documents separate live/historical tiers and cursor pagination; use the returned cutoff rather than assuming the live endpoint contains all history. [Official historical-data documentation](https://docs.kalshi.com/getting_started/historical_data).

The documented historical endpoints provide markets, trades, candles, and private orders/fills—not a full historical L2 snapshot/delta archive. Those sources can extend outcome/price analysis; they cannot reconstruct the missing queue/book path. [Historical endpoint list](https://docs.kalshi.com/getting_started/historical_data), [historical candles](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks).

### P1: Error handling and storage are not adequate for uninterrupted capture

[The CLI client factory](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/cli.py:111) supplies neither a rate limiter nor WebSocket authentication. REST raises on 429 without backoff/retry. A fixed 80 ms sleep per book is not an account-aware rate budget. The audit found 74 stored 429 failures, mostly old-market bootstrap requests.

Most writers perform direct Parquet writes with inferred schemas and second-resolution filenames. [BufferedParquetWriter](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/data/parquet_writer.py:9) has a count-triggered memory buffer, no timed flush, close/finally flush, crash journal, or atomic publish. It is not the actual live collection path. NOAA processed files are overwritten for the same requested date range; this directly explains the observed manifest mismatch risk. Per-run small files and eager concatenation will become expensive under event-level capture.

The decimal migration is code-only for existing history: saved book prices are still integer cents, depth floats, and three schema variants coexist. `diagonal_relaxed` is convenient, but is not a declared financial-unit/schema migration policy. Historical lost subpenny precision cannot be restored by casting.

### P1: Weather timestamps and update novelty are conflated

[Forecast collection](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/cli.py:617) writes `forecast_issue_ts = collection_ts`, captured before the requests finish. Source generation/update timestamps exist in version sidecars but are not part of the main modeling join. There is no distinction between source publication, first observed availability, request start, and completed receipt.

Using receipt time for an as-of join is generally conservative; relabeling it as issue time obscures latency and revisions. Backfilled forecasts must never be made available retroactively just because their source issue time is earlier. Repeated pulls of unchanged forecasts should retain polling evidence while deduplicating semantic versions.

NOAA fetches only the recent seven days, overwrites a range-named output, and does not maintain a missing-observation queue or page through long responses. Hence a prolonged outage leaves permanent gaps unless explicitly repaired. Other configured cities use airport-style station identifiers while the code prefixes them with `GHCND:`; station IDs must be validated before expansion. The YAML location settings and hardcoded CLI locations also disagree and are not a single authoritative mapping.

### P1: Health reports can produce reassuring but misleading numbers

[Collector health](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/monitoring/collector_reports.py:229) has several denominator/semantic problems:

- “Raw orderbook rows” are actually the same processed feature rows as “normalized orderbook rows.”
- `forecast_coverage_pct` is 100 whenever any forecast rows and any market rows exist; it does not check matching location/date/availability.
- “Latest market as-of” is the market's future `close_time`, not collection time.
- The `since` window applies to books/forecasts but not metadata/labels.
- Freshness only considers the newest book and forecast anywhere in the selection, not each required market/location or a successful valid book.
- Empty books, fetch errors, missing observations, and unavailable depth are not clearly separated operationally.

[Dataset validation](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/datasets/validation.py:104) does not enforce depth/continuity/station/forecast-target readiness. `unresolved_markets` counts rows, not unique markets. The newest registry says “passed” while holding 60 unresolved rows / 12 unresolved markets; the mode used for that pass is not recorded. Passing structural checks is not a trading-readiness certificate.

### P1: Current backtests cannot establish maker execution quality

[FillSimulator](/Users/vihaannarvekar/Documents/Projects/eventmm-kalshi/src/eventmm/backtest/fills.py:11) simulates taker fills and defaults to the requested quantity when depth is unknown. The stored main dataset has no depth. There is no passive queue model, cancel/replace latency, quote lifetime, L2 book-walking, or validated maker fill calibration. Repeated snapshots may reuse liquidity because no event tape reconciles depletion.

The portfolio/decimal/gate components are useful development foundations. Prior fill counts or profits are not evidence of executable market-making profitability. Aggregate L2 plus public trades will improve replay but still will not reveal exact queue position; own order/fill observations and explicit uncertainty bounds remain necessary.

## 3. Development plan and release gates

Effort below is a planning estimate for one developer familiar with this repository, not a promise. Some work can proceed concurrently, but collecting independent calendar days cannot be compressed into an engineering sprint. No spending/deployment decision is made by this plan.

| Phase | Work and principal files | Completion criteria | Indicative effort |
|---|---|---|---|
| 0: Preserve evidence and choose the initial universe | Freeze existing dataset/manifests; mark current outputs exploratory. Start with complete NYC daily event partitions; define station/source/day rules from archived market rules. Agree analysis vs execution dataset contracts. | Immutable baseline inventory; explicit instrument mapping; separate collection health, liquidity, research readiness, and trading readiness statuses. | 0.5–1 day |
| 1: Restore supervised capture immediately | Replace shell-only operation with a supervised long-running service on an always-on host. Reuse the new WS client, add public trades, persist raw envelopes before feature computation. Fix paginated discovery and 429 handling. Separate weather/metadata/labels from the book receiver. | At least 72 continuous hours; intentional process/network interruption recovers; raw data survives restart; errors alert rather than silently ending collection. Collection continues during later phases. | 2–4 days |
| 2: Make capture replayable and auditable | Add durable journal and atomic Parquet rotation; explicit decimal schemas/units; local ingest sequence, session ID, SID/exchange sequence, exchange/receive/write times; snapshots and gap intervals; periodic REST audits; dynamic enrollment/retirement. | Deterministic reconstruction from recorded bytes; zero silently bridged gaps; replay agrees with same-state checkpoints; every expected market has a coverage record. | 3–5 days |
| 3: Repair weather and settlement semantics | Daily-high target builder; local timezone/day and same-day policy; exact station join; source-time vs availability-time; semantic forecast versions; revised observation history; rule-aware settlement cross-checks. Replace incorrect station test and add multi-hour forecast regressions. | Reproduce then eliminate the measured hourly-vs-daily join discrepancy on eligible full-day inputs; no unverified station substitution; no future availability leakage; original raw lineage retained. | 3–5 days, alongside capture |
| 4: Backfill recoverable history and rebuild research datasets | Cutoff-aware market/trade/candle jobs with pagination/checkpoints; missing NOAA dates; refresh old unresolved labels; recover stored forecast vintages; immutable versioned dataset rebuild; recursive manifest verification. Update config aliases only after acceptance. | All requested backfill intervals are complete or explicitly marked unavailable; builds deterministic; independent dates and coverage reported; current datasets stop pointing silently at stale versions. | 2–4 days plus API runtime |
| 5: Build execution replay and paper integration | Public trade/L2 replay, latency-aware taker book-walking, conservative passive fills with bounds, private state reconciliation, durable intent/ack/cancel/fill records; integrate the trading gate at actual send time. | Gaps/staleness/closed markets block orders in replay and shadow mode; process restarts do not create duplicate orders; account reconciliation resolves all simulated in-flight operations. | 1–2 weeks |
| 6: Evaluate on untouched periods before live quoting | Hold out complete calendar dates across all event legs; fit only on earlier available outcomes; assess regimes, fees, inventory, adverse selection, and sensitivity to queue/latency assumptions. | Operational and statistical gates below pass; no reliance on optimistic unknown-depth fills or unverified labels. | Data accumulation measured in weeks/months |

**Critical path:** Phase 1 starts first because uncaptured books are irrecoverable. Phase 3 runs while collection accrues. Phase 4 restores recoverable breadth; it does not substitute for Phase 2's live tape. Infrastructure/replay development should continue before the sample is large enough for strategy selection.

### First implementation batches

1. **Collector entry point and supervision:** new `collect-market-data` service around `ws_client.py`; source workers with separate failure domains; no sklearn import in the collector process; graceful shutdown; single-instance lock; startup health, rolling logs, bounded reconnect backoff and alerting. Keep a minimal raw recorder deployable before the full feature system is finished.
2. **Discovery and metadata:** share the paginating loader; persist raw market/event/series responses with received timestamps and content hashes; preserve rules, price ranges and settlement fields; keep all legs of selected partitions even if some are illiquid; dynamically discover tomorrow's markets before they trade. Empty universes must not crash the pipeline.
3. **Journal and replay:** write original wire envelopes, including control/error messages that normalization rejects; build normalized tables as derived outputs. Add writer failure, disk-full, partial-file, duplicate-message, sequence-gap, reconnect and schema-change fault tests. Make backlog/lag a trading and collection-health input.
4. **Weather semantics and backfill:** exact settlement-station mapping; full-day/remaining-day target logic; DST/local-day fixtures; archival observation revisions; separate calibration outcomes from features available intraday; dedupe source versions without erasing collection latency evidence.
5. **Quality and publication:** replace misleading health fields, add per-market eligible-time coverage, pin immutable source manifests, run readiness-specific validation, and publish a new explicit dataset version. Preserve old datasets for comparison; do not mutate evidence under an old version name.
6. **Execution integration:** implement REST snapshot reconciliation while continuing to buffer/sequence private updates; use version/watermark checks rather than a blind resume flag; persist unresolved actions across restart; gate every new/amended order at the send boundary and define a cancellation/escalation policy for already-resting orders.

## 4. What must be captured going forward

| Stream/table | Required content | Collection policy |
|---|---|---|
| Raw exchange journal | Original envelope, type/channel, connection/session ID, command ID, SID, sequence if present, event timestamp if present, UTC receive time, monotonic local receive order, ingest ID, schema/config version | Every message; no five-minute downsampling of the primary archive |
| L2 books | Initial/recovery snapshots, all price/quantity deltas, validation outcomes, gaps and recovery boundaries, both binary legs | Event driven; periodic checkpoints and independently recorded snapshot audits |
| Public trades | Trade ID, market, price, quantity, taker direction, exchange/receive times | Every trade; dedupe by exchange identity; REST backfill where possible |
| Market/rule versions | Market/event/series identity, status, open/close/settlement times, contract rules, exact station, price ranges, fees/overrides | Discovery at startup and rollover, lifecycle-triggered refresh, periodic reconciliation |
| Private execution | Intent/client order ID, requests/responses, orders, fills, positions, groups, subaccount, fees, cancellation and reconciliation results | Every event; separate restricted archive; never assume public tape replaces this |
| Forecast versions | Source issue/update time, first received time, valid period/local date, station/grid mapping, hourly values, raw hash and path | Poll on a modest source-appropriate schedule initially; store only new semantic versions plus lightweight poll receipts |
| Observations/outcomes | Station-specific intraday readings, official daily values and revision timestamps, exchange results, rule cross-check, time label became known | Intraday where used in signals; daily delayed-result polling; retry a durable missing-date queue |
| Derived research features | Prices/depth, imbalance, trade intensity, book age, valid-state flag, forecast/metadata version IDs, horizon and label provenance | Event/decision-time or explicitly sampled outputs derived from the archive, with clear units |

Do not record request authentication headers, tokens, or signing keys. Public and private data have different access requirements. Keep decimal dollar/cent conversion explicit at schema boundaries.

A short collection pilot should measure events/second, burst rate, bytes/event, compression, and replay throughput before capacity is chosen. Storage estimate: `events_per_second × mean_bytes_per_event × 86,400 × retention_days`, adjusted using measured compression and checkpoint overhead. Current processed source data is only about 15.8 MB; the bottleneck today is capture completeness and meaning, not local storage volume.

## 5. Acceptance targets for “enough data”

These are proposed engineering/evaluation gates, not statistical guarantees of profitability.

| Gate | Proposed threshold or invariant |
|---|---|
| Initial reliable capture | 72-hour soak, followed by seven days with at least 99.5% observed subscription availability during selected markets' eligible trading windows |
| Data loss | Every disconnect/sequence gap/writer failure is explicit; never silently interpolate a tradable book across a gap |
| Replay | All valid archived segments replay deterministically; checksum comparison at captured checkpoints; REST comparisons account for observation-time differences |
| Freshness | Per-market receive/audit freshness and per-location forecast availability tracked separately. Calibrate a tighter execution threshold from measured latency; the current 30-second default is not a validated quoting SLA |
| Durable ingestion | Published target for loss window and recovery time, measured by process-kill/disk tests; monitor durable ingest watermark, queue lag and disk headroom |
| Metadata | Every quoted market has verified rule/station mapping, current grid/status/close time, and complete parent event membership |
| Weather/outcomes | Model inputs use only values available then; missing/revised/late observations explicit; every supervised row has a justified label; station mismatches quarantined |
| Research sample | First checkpoint at 30 settled event dates; target 60–90 settled calendar dates with at least 20 untouched held-out dates before serious strategy selection |
| Breadth | Stabilize NYC first, then add two or three validated locations/series. Cluster splits and uncertainty by calendar date/event; six sibling contracts or correlated cities are not independent trials |
| Execution sample | At least ten complete market sessions across active, quiet, near-close and forecast-change periods for initial replay development; thousands of order opportunities may help calibration but do not replace held-out days |
| Paper readiness | At least two weeks of continuous shadow/paper operation with documented recovery and no unresolved reconciliation faults; passive fill results reported under conservative queue/latency scenarios |
| Live readiness | Actual order transport cannot bypass the invalid-state gate; already-resting order behavior is tested; profitability evidence survives costs and conservative execution assumptions |

Availability and liquidity must have separate denominators. A valid one-sided market can be faithfully collected but be unsuitable for the chosen quoting strategy. Do not force every market to look two-sided to achieve a collection KPI. Retain empty and one-sided states in the archive and exclude them from trading according to an explicit strategy rule.

## 6. What can be repaired versus what must be collected anew

- **Repair from local raw data:** reconstruct daily forecast targets and source-version history; normalize schemas; fix misleading registry/health calculations; verify lineage; regenerate derived features with explicit availability semantics.
- **Repair by external backfill:** missing station observations, current settlement outcomes, historical market metadata, available trades/candles. Availability and endpoint cutoffs must be checked, and unavailable intervals must remain marked missing.
- **Cannot infer from existing summaries:** lost subpenny precision, missing historical L2 depth/deltas, queue evolution, trade/cancel attribution, actual receive latency, and unrecorded own order lifecycles. These require forward capture or an independently verified archival source.
- **Do not recycle as evidence:** optimistic assumed-depth fills, the old profit report, inflated repeated-label/forecast row counts, or the generic registry “passed” status.

The immediate development decision should be to ship the supervised raw market-data recorder and correct the weather/settlement joins. Keep building replay, risk, and execution infrastructure as new event days accrue; defer conclusions about strategy profitability until both the data-quality and held-out evaluation gates are met.

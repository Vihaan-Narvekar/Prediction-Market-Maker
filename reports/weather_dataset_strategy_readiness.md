# Weather Dataset Strategy Readiness

Date: 2026-07-11

## Finding

The dataset is large enough to build strategy, simulation, risk, and evaluation
infrastructure. It is not large enough to conclude that a predictive or
market-making strategy is profitable.

Development should continue now using the current data for structural and
microstructure work. More collection is a parallel evidence-building track, not
a blocker for partition tooling, conservative execution simulation, monitoring,
or paper-trading architecture.

## Effective size

| Measure | Value |
| --- | ---: |
| Snapshot rows | 4,410 |
| Markets | 42 |
| Contract dates | 7 |
| Settled contract dates | 6 |
| Settled markets | 36 |
| Full market/weather usable rows | 2,157 |
| Rows with midpoint | 2,409 |
| Rows with forecast | 4,410 |
| Rows with top-of-book depth | 0 |

Rows are repeated observations of the same contracts. The effective independent
sample is closer to six settled event dates than 4,410 rows.

## Walk-forward evidence

Only two held-out dates are currently evaluable after requiring three earlier
training dates and complete market/weather features. Market midpoint and
microprice outperform logistic regression on both held-out dates. The sample is
too small for confidence intervals, seasonal robustness, or model selection.

## What can begin now

- Executable YES/NO edge research.
- Market and partition consistency monitors.
- Conservative taker simulation.
- Position and event-limit testing.
- Fee-aware strategy rejection tests.
- Paper architecture and collector reliability work.

## What should wait

- Live quoting.
- Capital allocation based on model performance.
- Claims of calibrated edge.
- Passive market-making profitability estimates.
- Strategy selection based on the current two held-out dates.

## Collection target

Minimum target before serious paper market-making evaluation:

- 30 settled contract dates, ideally 60–90 across different weather regimes.
- At least 20 untouched held-out dates.
- Reliable top-level price and depth for both sides.
- Collector freshness within the configured interval.
- Independent settlement/observation verification.

The current collector is stale by roughly ten days and should be restarted before
additional modeling work. The new freshness command exits non-zero when books or
forecasts exceed the age threshold.

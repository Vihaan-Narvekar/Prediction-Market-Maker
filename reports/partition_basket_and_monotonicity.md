# Partition Basket and Monotonicity Report

Date: 2026-07-11

Dataset: `weather_nyc_main_v1_features`

## Partition construction

- Minute-level event buckets: 742
- Structurally complete six-leg partitions: 724
- Required structure: one lower tail, four ranges, one upper tail
- Complete partitions with known stored depth: 0
- Complete partitions using assumed depth: 724

The historical dataset predates top-level depth retention. New collector rows now
store YES/NO top-level depth and future simulations will identify those fills as
`known` rather than `assumed`.

## Fee-adjusted basket opportunities

- Positive long-YES basket opportunities after current fees: 0
- Positive long-NO basket opportunities after current fees: 0
- Complete atomic side simulations: 728
- Positive guaranteed atomic simulations: 0
- Incomplete partial side simulations: 720

Earlier gross reports found sums below/above the 100-cent partition bound. Those
deviations do not survive the current Kalshi fee schedule when six one-contract
orders are charged separately. The partition monitor remains valuable, but the
existing sample does not demonstrate executable basket arbitrage.

## Monotonicity

- Executable tail monotonicity violations: 0

A violation is only reported when the more difficult tail's executable bid
crosses the easier tail's executable ask (or the equivalent lower-tail
relationship). Midpoint-only inversions are not classified as arbitrage.

## Forecast revisions

- Daily-high forecast versions: 3,139
- Non-zero daily-high revisions: 223

Hourly NWS periods are first aggregated to the maximum forecast temperature for
each location, forecast date, and issue timestamp. Revision features then record
the prior issue, temperature change, minutes since prior issue, and running
high/low forecast.

## Outputs

Generated outputs under `artifacts/research/` include partition features,
monotonicity violations, atomic and partial basket summaries, fill-level records,
and daily forecast revisions. Artifacts are intentionally Git-ignored.

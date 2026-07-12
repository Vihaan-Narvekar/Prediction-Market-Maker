# Forecast Revision Event Study

Date: 2026-07-12

Dataset: `weather_nyc_revision_v2_features`

## Method

NWS hourly forecast periods are aggregated to a daily-high forecast for each
location, forecast date, and issue timestamp. Nonzero daily-high revisions are
aligned to the latest valid market quote within 30 minutes before the issue and
the first valid quote at or after these targets:

- first post-revision quote
- 1 minute
- 5 minutes
- 15 minutes
- 30 minutes

The first quote within 20 minutes after each target is selected. Both target time
and actual quote delay are retained. All timestamps are normalized to UTC.

## Available overlap

- Revision IDs with a valid pre-event quote: 13
- Revisions with at least one post-event quote: 12
- Markets: 29
- Events: 5
- Detailed pre/post observations: 297
- Complete six-leg revision/horizon partitions: 30
- Observations with known historical depth: 0
- Observations with missing depth: 297

## Aggregate response

| Horizon | Revisions | Market observations | Mean midpoint change | Mean microprice change | Mean spread change | Directional hit rate | Direction-adjusted midpoint change | Median actual quote delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| First post | 12 | 50 | 0.03 | 0.214 | -0.26 | 14.6% | -0.50 | 5.11 min |
| 1 minute | 12 | 50 | 0.03 | 0.214 | -0.26 | 14.6% | -0.50 | 4.11 min |
| 5 minutes | 12 | 50 | 0.07 | 0.251 | -0.26 | 14.6% | -0.46 | 0.12 min |
| 15 minutes | 11 | 49 | -0.04 | 0.295 | -0.12 | 31.9% | 0.13 | 0.41 min |
| 30 minutes | 9 | 42 | -0.07 | 0.085 | -0.24 | 27.5% | -0.41 | 0.90 min |

Eighteen revision/market pairs show at least a one-cent move in the expected
direction at one of the observed horizons. Their median first detected
incorporation time is 15.37 minutes.

## Partition response

For complete partitions, mean changes in the six-leg midpoint sum are -1.1,
-0.7, -1.9, and -2.1 cents at 1, 5, 15, and 30 minutes respectively. Mean
absolute normalized leg-probability changes range from 0.68 to 1.24 percentage
points. Partial partitions are excluded from partition probability calculations.

## Interpretation

This sample does not show consistent immediate movement in the contract-aware
forecast direction. The 15-minute horizon is the only aggregate horizon with a
positive direction-adjusted midpoint response, and the study contains only 12
post-event revisions. The result is exploratory rather than evidence of a
tradeable latency effect.

The event rows now compute contract settlement probability by applying the
expanding historical NWS daily-high error distribution to the forecast level.
Only errors from earlier contract dates are eligible. The estimator first uses
matching lead-time and revision-direction buckets when at least 10 samples are
available, backs off to lead time, then to all earlier dates, and applies
Jeffreys smoothing. All 297 rows have an estimate, with sample sizes from 10 to
235. These probabilities drive the fee-adjusted executable YES and NO edge
columns. The deterministic `forecast_event_indicator` is retained only for
direction diagnostics and never drives executable edge.

This is a leakage-safe empirical baseline, not yet a production-calibrated fair
value model. Repeated forecast versions are observations in its error
distribution, the sample spans few realized weather dates, and the largest
apparent edges remain implausibly high. Economic interpretation therefore
requires walk-forward calibration diagnostics and a larger set of independent
contract dates before any live trading decision.

Depth changes cannot be evaluated in this historical sample because depth was
not retained. Newly collected snapshots include depth and will populate this
field in future dataset versions.

## Outputs

- `artifacts/research/weather_nyc_revision_v2_features_forecast_event_study.parquet`
- `artifacts/research/weather_nyc_revision_v2_features_forecast_event_study_summary.csv`

These generated artifacts are Git-ignored. The reusable implementation is in
`src/eventmm/research/forecast_event_study.py`.

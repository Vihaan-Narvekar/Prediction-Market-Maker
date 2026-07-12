# Weather Logistic Model Card

## Status

Research prototype only. Not approved for live trading or autonomous quoting.

## Intended use

Estimate the probability that a NYC daily-high temperature contract settles YES,
then compare that probability with executable YES and NO asks. The model is a
baseline for research and must not be treated as a calibrated production model.

## Dataset

- Dataset: `weather_nyc_main_v1_features`
- Snapshot rows: 4,410
- Markets: 42
- Contract dates: 7
- Settled markets: 36 across 6 dates
- Rows usable by the full `weather_market` feature set: 2,157
- Top-of-book depth columns: unavailable in this historical dataset

Repeated snapshots from one contract are correlated. Contract date, not row
count, is the primary independent evaluation unit.

## Features

- Forecast-minus-threshold
- Absolute forecast distance to threshold
- Contract-aware forecast event indicator
- Market midpoint
- Market spread
- Time to expiry

## Evaluation design

Expanding contract-date walk-forward evaluation uses only earlier dates for
training and one later date for testing. With three minimum training dates and
complete feature rows, only two held-out dates are currently evaluable.

| Test date | Model | Log loss | Brier | ROC AUC |
| --- | --- | ---: | ---: | ---: |
| 2026-06-29 | Logistic | 0.6116 | 0.2112 | 0.6214 |
| 2026-06-29 | Market midpoint | 0.4394 | 0.1527 | 0.6868 |
| 2026-06-29 | Microprice | 0.4418 | 0.1532 | 0.6859 |
| 2026-06-30 | Logistic | 0.3744 | 0.1271 | 0.8627 |
| 2026-06-30 | Market midpoint | 0.2643 | 0.0814 | 0.9805 |
| 2026-06-30 | Microprice | 0.2665 | 0.0820 | 0.9793 |

The logistic model does not beat the market baselines on either held-out date.
No model-driven live strategy is justified by this sample.

Weighted across the 878 held-out snapshot rows, logistic log loss/Brier are
0.4665/0.1598, versus 0.3323/0.1091 for midpoint and 0.3346/0.1096 for
microprice. These row-weighted summaries remain subordinate to the date-level
comparison because there are only two test dates.

## Limitations

- Only two evaluable test dates.
- One city and one weather-market family.
- Missing top-level depth on the historical feature dataset.
- Repeated intraday rows create strong within-contract dependence.
- No fitted probability calibration on an independent validation window.
- NWS forecasts are deterministic inputs and may share errors across contracts.
- The present contract parser and settlement verification cover a narrow domain.

## Promotion requirements

Before paper market making, collect at least 30 settled contract dates, with a
preference for 60–90 dates across seasons. Require at least 20 genuinely held-out
dates, stable calibration, net executable edge after verified fees, and positive
results under conservative depth and latency assumptions.

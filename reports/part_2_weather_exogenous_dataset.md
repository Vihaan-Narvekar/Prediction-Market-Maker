# Part 2: Weather Exogenous Data and Outcome Dataset

## Objective
Build a no-leakage research dataset joining Kalshi weather markets to NWS forecasts, NOAA observations, and settlement labels.

## Data Sources
- Kalshi market metadata and order-book snapshot features
- NWS hourly forecasts
- NOAA daily observations

## Contract Parsing
Weather market titles are converted into structured threshold contracts with location, date, threshold, unit, and comparison operator.

## As-Of Join Logic
Forecast rows are joined only when `forecast_issue_ts <= as_of_ts`.

## Dataset Validation
- dataset: weather_nyc_main_v1
- rows: 4410
- markets: 42
- future leakage rows: 0
- missing labels: 264
- missing forecast rows: 0

## Next Step
Part 3: fair-value modeling and calibration.

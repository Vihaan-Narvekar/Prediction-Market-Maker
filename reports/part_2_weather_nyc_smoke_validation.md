# Part 2 Weather NYC Smoke Validation

Dataset name: weather_nyc_smoke_v1
Rows: 138
Markets: 138
Start: 2026-06-23 23:19:53.494697
End: 2026-06-23 23:20:09.302179

## Validation
- duplicate market_ticker/as_of_ts rows: 0
- future forecast leakage rows: 0
- missing labels: 6
- missing forecast rows: 132
- missing thresholds: 0
- impossible temperatures: 0
- unresolved markets: 6

Dataset failed validation because: Unresolved labels detected.
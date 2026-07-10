# Part 2 Weather NYC Main Validation

Dataset name: weather_nyc_main_v1
Rows: 4410
Markets: 42
Start: 2026-06-25 20:52:42.331178
End: 2026-07-02 02:59:31.632291

## Validation
- duplicate market_ticker/as_of_ts rows: 0
- future forecast leakage rows: 0
- missing labels: 264
- missing forecast rows: 0
- missing thresholds: 0
- impossible temperatures: 0
- unresolved markets: 264

Dataset is valid for live/inference use with unresolved labels allowed.

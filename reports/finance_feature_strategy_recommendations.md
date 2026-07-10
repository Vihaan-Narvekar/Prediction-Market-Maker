# Finance Feature and Strategy Recommendations

Date: 2026-07-03

Dataset: `weather_nyc_main_v1_features`

## Executive Summary

The collected weather/order-book data is usable for finance-specific strategy research, but the first implementation priority is not a more complex model. It is to make the trading engine executable and contract-aware.

The EDA found:

- `4,410` dataset rows across `42` markets.
- `2,409` rows with usable order-book mid/spread data.
- `2,157` rows usable for the current `weather_market` feature set.
- Median spread is `1` cent; 90th percentile spread is `2` cents.
- No single-market crossed or locked bid books were found.
- Full six-leg weather partitions exist for `237` minute snapshots.
- Partition baskets show structural relative-value opportunities:
  - `101` snapshots where `sum_yes_bid > 100`, making the long-NO basket theoretically attractive.
  - `15` snapshots where `sum_yes_ask < 100`, making the long-YES basket theoretically attractive.
  - Maximum one-minute executable basket edge observed: `6` cents on rich YES bids, `3` cents on cheap YES asks.

Important correction made during research:

- Weather threshold parsing now distinguishes `<` and `>` contracts.
- Baseline weather features now include `forecast_event_indicator`, which handles `<`, `>`, and `range` contracts correctly.
- The model feature set now uses `forecast_event_indicator` instead of assuming every market is an above-threshold contract.

## Features To Implement

### 1. Executable Quote Features

Add these to the dataset or a strategy feature layer:

- `yes_bid_cents`
- `yes_ask_cents`
- `no_bid_cents`
- `no_ask_cents`
- `market_mid_cents`
- `market_spread_cents`
- `microprice_cents`
- `microprice_minus_mid_cents`

Justification:

Strategies must trade against executable bid/ask, not midpoint. The current book is often 1 cent wide, so a midpoint backtest can overstate edge materially.

### 2. Contract-Aware Weather Features

Keep and standardize:

- `forecast_minus_threshold`
- `abs_forecast_distance_to_threshold`
- `forecast_event_indicator`

Add:

- `forecast_distance_to_lower_bound`
- `forecast_distance_to_upper_bound`
- `forecast_inside_range`
- `contract_side_type`: `lower_tail`, `upper_tail`, `range`

Justification:

Weather markets are not homogeneous. A `<79`, `>86`, and `79-80` range contract require different event logic.

### 3. Fair-Value Edge Features

For a calibrated model probability `p_model`:

- `yes_edge_to_ask_cents = p_model * 100 - yes_ask_cents`
- `yes_edge_to_mid_cents = p_model * 100 - market_mid_cents`
- `no_edge_to_ask_cents = (1 - p_model) * 100 - no_ask_cents`
- `no_edge_to_mid_cents = (1 - p_model) * 100 - (100 - market_mid_cents)`

Justification:

These convert model output into executable trading signals. The strategy should not ask, “is model above midpoint?” It should ask, “can I buy YES or NO with enough edge after fees and slippage?”

### 4. Partition Basket Features

For each contract date and timestamp, construct the full six-leg mutually exclusive weather partition:

- lower-tail threshold contract
- four range contracts
- upper-tail threshold contract

Add:

- `partition_leg_count`
- `partition_sum_yes_bid_cents`
- `partition_sum_yes_ask_cents`
- `partition_short_basket_edge_cents = sum_yes_bid - 100`
- `partition_long_basket_edge_cents = 100 - sum_yes_ask`
- `partition_mid_sum_richness_cents = sum_mid - 100`
- `partition_max_leg_spread_cents`
- `partition_all_legs_present`

Justification:

This is the strongest structural finance-specific opportunity in the EDA. The six contracts are mutually exclusive and collectively exhaustive for the daily high-temperature bucket. If all six legs are executable, basket mispricing can create bounded-risk or locked-profit trades.

### 5. Market-Making Features

Add:

- rolling spread median by market
- rolling mid volatility
- rolling microprice-minus-mid mean
- depth imbalance slope/change
- quote age
- forecast age
- event-date inventory
- partition inventory

Justification:

The median spread is already 1 cent, so market making should be selective. Quote placement should depend on fair value, imbalance, quote age, and inventory, not static spread alone.

## Strategies To Implement

### Strategy 1: Partition Basket Arbitrage

Implement first.

Rules:

1. Group contracts by `contract_date` and timestamp bucket.
2. Require exactly six unique legs.
3. Use the latest quote per leg per timestamp.
4. Compute:
   - `sum_yes_ask`
   - `sum_yes_bid`
5. If `sum_yes_ask + cost_buffer < 100`, buy one YES in every leg.
6. If `sum_yes_bid - cost_buffer > 100`, buy one NO in every leg.
7. Require all-or-none execution.

Why buying NO works:

For six mutually exclusive contracts, exactly one YES pays and five NO contracts pay. Buying one NO in every leg costs `600 - sum_yes_bid` cents and pays `500` cents. Profit exists when `sum_yes_bid > 100`.

Minimum implementation:

- `PartitionBasketStrategy`
- `PartitionBasketEvent`
- basket-aware fill simulator
- all-or-none fill mode
- per-leg max spread filter
- per-event exposure cap

Recommended initial thresholds:

- `min_basket_edge_cents >= 3`
- `max_leg_spread_cents <= 2`
- require all six legs non-null
- require quote timestamps within one minute

### Strategy 2: Executable Fair-Value Taker

Rules:

1. Train/calibrate `p_model`.
2. Buy YES if `p_model * 100 - yes_ask_cents > min_edge_cents`.
3. Buy NO if `(1 - p_model) * 100 - no_ask_cents > min_edge_cents`.
4. Skip if spread is too wide or model calibration confidence is low.

Recommended initial thresholds:

- `min_edge_cents >= 5`
- `market_spread_cents <= 2`
- `time_to_expiry_hours` filter after more near-expiry data is collected

Justification:

This turns model output into executable edge. It should replace midpoint-based signal backtests.

### Strategy 3: Relative-Value Market Making

Rules:

1. Maintain a fair value `p_model`.
2. Quote YES bid below fair value and YES ask above fair value.
3. Widen or stop quoting when:
   - spread is already 1 cent and edge is insufficient,
   - inventory is concentrated in one event date,
   - partition basket is structurally rich/cheap against the quote.

Recommended quote logic:

- Join bid only if `p_model * 100 - best_yes_bid >= maker_edge_cents`.
- Join ask only if `best_yes_ask - p_model * 100 >= maker_edge_cents`.
- Use microprice and depth imbalance to skew quote size.

Justification:

The book is usually tight. Market making is viable only if the model/fair-value estimate prevents adverse selection.

### Strategy 4: Relative-Value Ladder Monitor

Rules:

- For `>` thresholds, higher thresholds should not have higher YES value.
- For `<` thresholds, higher thresholds should not have lower YES value.
- Across all six partition legs, mid-sum should be near 100.

Current EDA:

- After fixing contract semantics, no tail monotonicity violations were detected.
- Partition basket mispricing remains present and actionable.

Recommendation:

Implement this first as a monitor, not a trading strategy. Promote to trading only after executable basket fills are simulated.

## Backtest Engine Changes Needed

1. Add executable bid/ask fills.
2. Reject midpoint fills for taker strategies.
3. Add all-or-none basket execution.
4. Add event-date exposure accounting.
5. Add partition-aware settlement.
6. Report PnL attribution:
   - model edge
   - spread paid/captured
   - fees
   - slippage
   - basket locked edge

## Training Engine Changes Needed

1. Use `forecast_event_indicator` in weather feature sets.
2. Train with temporal contract-date splits.
3. Add calibration reports by:
   - contract type
   - spread bucket
   - edge bucket
   - contract date
4. Add probability outputs to the dataset:
   - `p_model`
   - `p_market_mid`
   - `p_microprice`
5. Persist dataset hash and feature set in the model registry.

## Priority Order

1. Partition basket feature builder.
2. Executable bid/ask edge columns.
3. Taker fill simulator using bid/ask, not midpoint.
4. `PartitionBasketStrategy` with all-or-none execution.
5. Calibrated fair-value model using contract-aware features.
6. Inventory-aware market-making strategy.
7. PnL attribution and risk dashboard.

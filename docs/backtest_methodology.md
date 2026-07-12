# Backtest Methodology

## Purpose

The backtester is a research simulator for testing event-market mechanics. It is
not a forecast of live performance.

## Data and time ordering

- Replay rows in `as_of_ts` order.
- Forecasts must satisfy `forecast_issue_ts <= as_of_ts`.
- Model selection and evaluation must use expanding contract-date folds.
- Never split repeated snapshots from the same contract date across train and test.
- Dataset manifests record exact output and source hashes for reproducibility.

## Signals

Model probabilities are translated to executable cents:

- `YES edge = p_yes * 100 - best_yes_ask`
- `NO edge = (1 - p_yes) * 100 - best_no_ask`

Midpoint edge may be reported diagnostically but must not trigger taker fills.

## Fill assumptions

- Taker buys fill at the executable ask; sells fill at the executable bid.
- When top-level depth is available, filled quantity is capped at that depth.
- When depth is missing, the simulator currently falls back to the requested
  quantity. Results using that fallback must be labeled optimistic.
- Displayed liquidity is not yet consumed across concurrent strategies or
  repeated snapshots, so current backtests can still reuse liquidity.
- Latency, queue position, partial multi-level fills, and market impact remain
  future work.

## Fees

The default general taker fee starts with
`ceil_to_centicent(0.07 * contracts * price * (1-price))` in dollars and then
rounds the whole-contract, whole-cent-price order charge up to a cent, matching
the published fee table. The default maker multiplier is zero; configured
non-standard series may differ. This follows
Kalshi's fee schedule effective July 7, 2026:
https://kalshi.com/docs/kalshi-fee-schedule.pdf

The exchange can change series multipliers. Before every live or paper-trading
run, verify the current schedule and `GET /series/fee_changes`. The simulator
does not model fractional-contract or subpenny fill-level rounding accumulators
and rebates.
Simple binary settlement has no settlement fee.

## Risk controls

Every run config sets:

- Maximum absolute position per market.
- Maximum gross exposure per event.

Orders that would exceed a limit are rejected before fill simulation. These are
basic research controls, not a complete live risk system.

## Required reporting

Report train/test contract dates, orders, fills, fill rate, fees, gross and net
PnL, position concentration, and whether depth fallback was used. Strategy
comparisons should aggregate first by contract date and include uncertainty once
the sample is large enough.

## Known optimistic assumptions

- No latency or adverse selection.
- No queue model.
- Missing depth falls back to requested quantity.
- Displayed liquidity is not depleted across time.
- No order rejection, disconnect, or stale-quote simulation.

Until these are addressed, backtests are useful for rejecting weak strategies,
not confirming deployable profitability.

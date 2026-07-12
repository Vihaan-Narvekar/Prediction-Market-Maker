from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import polars as pl

from eventmm.backtest.events import FillEvent, MarketDataEvent, OrderEvent
from eventmm.backtest.fees import FeeModel
from eventmm.backtest.fills import FillSimulator


def _leg_type(row: dict) -> str:
    if row.get("contract_type") == "range":
        return "range"
    return "lower_tail" if row.get("comparison_operator") == "<" else "upper_tail"


def build_partition_features(
    df: pl.DataFrame,
    *,
    bucket_every: str = "1m",
    quantity: int = 1,
    fee_model: FeeModel | None = None,
) -> pl.DataFrame:
    fee_model = fee_model or FeeModel()
    required = {
        "event_ticker",
        "market_ticker",
        "as_of_ts",
        "contract_type",
        "comparison_operator",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing partition columns: {sorted(missing)}")
    bucketed = (
        df.with_columns(
            pl.col("as_of_ts")
            .cast(pl.Datetime)
            .dt.truncate(bucket_every)
            .alias("quote_bucket")
        )
        .sort("as_of_ts")
        .unique(["event_ticker", "quote_bucket", "market_ticker"], keep="last")
    )
    rows = []
    for key, group in bucketed.group_by(
        ["event_ticker", "quote_bucket"], maintain_order=True
    ):
        legs = group.to_dicts()
        leg_types = [_leg_type(row) for row in legs]
        complete = (
            len(legs) == 6
            and leg_types.count("lower_tail") == 1
            and leg_types.count("upper_tail") == 1
            and leg_types.count("range") == 4
        )
        yes_asks = [row.get("best_yes_ask") for row in legs]
        no_asks = [row.get("best_no_ask") for row in legs]
        yes_bids = [row.get("best_yes_bid") for row in legs]
        spreads = [row.get("market_spread") for row in legs]
        executable_yes = complete and all(value is not None for value in yes_asks)
        executable_no = complete and all(value is not None for value in no_asks)
        yes_bid_total = sum(float(v) for v in yes_bids if v is not None)
        yes_ask_total = sum(float(v) for v in yes_asks if v is not None)
        no_ask_total = sum(float(v) for v in no_asks if v is not None)
        yes_fee = (
            sum(
                fee_model.estimate_fee_cents(float(price), quantity, "taker")
                for price in yes_asks
                if price is not None
            )
            if executable_yes
            else None
        )
        no_fee = (
            sum(
                fee_model.estimate_fee_cents(float(price), quantity, "taker")
                for price in no_asks
                if price is not None
            )
            if executable_no
            else None
        )
        depth_columns = ["yes_ask_depth_1", "no_ask_depth_1"]
        depth_known = all(
            column in group.columns and group[column].is_not_null().all()
            for column in depth_columns
        )
        rows.append(
            {
                "event_ticker": key[0],
                "quote_bucket": key[1],
                "partition_leg_count": len(legs),
                "partition_all_legs_present": complete,
                "partition_sum_yes_bid_cents": yes_bid_total
                if complete and all(v is not None for v in yes_bids)
                else None,
                "partition_sum_yes_ask_cents": yes_ask_total
                if executable_yes
                else None,
                "partition_sum_no_ask_cents": no_ask_total if executable_no else None,
                "partition_max_leg_spread_cents": max(
                    v for v in spreads if v is not None
                )
                if any(v is not None for v in spreads)
                else None,
                "long_yes_fee_cents": yes_fee,
                "long_no_fee_cents": no_fee,
                "long_yes_net_edge_cents": 100 * quantity
                - yes_ask_total * quantity
                - yes_fee
                if executable_yes and yes_fee is not None
                else None,
                "long_no_net_edge_cents": 500 * quantity
                - no_ask_total * quantity
                - no_fee
                if executable_no and no_fee is not None
                else None,
                "depth_source": "known" if depth_known else "assumed",
            }
        )
    return pl.DataFrame(rows)


def build_monotonicity_violations(
    df: pl.DataFrame, *, bucket_every: str = "1m"
) -> pl.DataFrame:
    bucketed = (
        df.with_columns(
            pl.col("as_of_ts")
            .cast(pl.Datetime)
            .dt.truncate(bucket_every)
            .alias("quote_bucket")
        )
        .sort("as_of_ts")
        .unique(["event_ticker", "quote_bucket", "market_ticker"], keep="last")
    )
    rows = []
    tails = bucketed.filter(
        (pl.col("contract_type") != "range")
        & pl.col("best_yes_bid").is_not_null()
        & pl.col("best_yes_ask").is_not_null()
    )
    for key, group in tails.group_by(
        ["event_ticker", "quote_bucket", "comparison_operator"], maintain_order=True
    ):
        ordered = group.sort("threshold_value").to_dicts()
        for left, right in zip(ordered, ordered[1:]):
            operator = key[2]
            violation = (
                operator == ">" and right["best_yes_bid"] > left["best_yes_ask"]
            ) or (operator == "<" and right["best_yes_ask"] < left["best_yes_bid"])
            if violation:
                rows.append(
                    {
                        "event_ticker": key[0],
                        "quote_bucket": key[1],
                        "comparison_operator": operator,
                        "lower_threshold": left["threshold_value"],
                        "higher_threshold": right["threshold_value"],
                        "lower_bid": left["best_yes_bid"],
                        "lower_ask": left["best_yes_ask"],
                        "higher_bid": right["best_yes_bid"],
                        "higher_ask": right["best_yes_ask"],
                    }
                )
    return pl.DataFrame(rows)


@dataclass(frozen=True)
class BasketSimulation:
    event_ticker: str
    quote_bucket: datetime
    side: str
    mode: str
    requested_legs: int
    filled_legs: int
    complete: bool
    total_cost_cents: float
    total_fees_cents: float
    guaranteed_payoff_cents: float
    guaranteed_pnl_cents: float | None
    known_depth_fills: int
    assumed_depth_fills: int
    fills: list[FillEvent]


def simulate_partition_basket(
    group: pl.DataFrame,
    *,
    side: Literal["yes", "no"],
    mode: str = "all_or_none",
    quantity: int = 1,
    fee_model: FeeModel | None = None,
) -> BasketSimulation:
    if side not in {"yes", "no"} or mode not in {"all_or_none", "partial"}:
        raise ValueError("Unsupported basket side or mode.")
    fee_model = fee_model or FeeModel()
    simulator = FillSimulator(fee_model)
    fills: list[FillEvent] = []
    for row in group.to_dicts():
        ask = row.get(f"best_{side}_ask")
        if ask is None:
            continue
        depth = row.get(f"{side}_ask_depth_1")
        event = MarketDataEvent(
            ts=row["as_of_ts"],
            market_ticker=row["market_ticker"],
            best_yes_bid=row.get("best_yes_bid"),
            best_yes_ask=row.get("best_yes_ask"),
            market_mid=row.get("market_mid"),
            market_microprice=row.get("market_microprice"),
            spread=row.get("market_spread"),
            depth_imbalance=row.get("market_depth_imbalance"),
            yes_ask_depth=depth if side == "yes" else row.get("yes_ask_depth_1"),
            no_ask_depth=depth if side == "no" else row.get("no_ask_depth_1"),
        )
        order = OrderEvent(
            ts=row["as_of_ts"],
            market_ticker=row["market_ticker"],
            side=side,
            action="buy",
            order_type="marketable_limit",
            price_cents=float(ask),
            quantity=quantity,
        )
        fill = simulator.simulate_taker_fill(order, event)
        if fill is not None:
            fills.append(fill)
    if mode == "all_or_none" and (
        len(fills) != 6 or any(fill.quantity < quantity for fill in fills)
    ):
        fills = []
    complete = len(fills) == 6 and all(fill.quantity == quantity for fill in fills)
    cost = sum(fill.price_cents * fill.quantity for fill in fills)
    fees = sum(fill.fee_cents for fill in fills)
    payoff = (100 if side == "yes" else 500) * quantity if complete else 0
    return BasketSimulation(
        event_ticker=str(group["event_ticker"][0]),
        quote_bucket=group["quote_bucket"][0],
        side=side,
        mode=mode,
        requested_legs=6,
        filled_legs=len(fills),
        complete=complete,
        total_cost_cents=cost,
        total_fees_cents=fees,
        guaranteed_payoff_cents=payoff,
        guaranteed_pnl_cents=payoff - cost - fees if complete else None,
        known_depth_fills=sum(fill.depth_source == "known" for fill in fills),
        assumed_depth_fills=sum(fill.depth_source == "assumed" for fill in fills),
        fills=fills,
    )

import json
from dataclasses import asdict
from pathlib import Path

import polars as pl

from eventmm.backtest.data_loader import load_backtest_dataset
from eventmm.backtest.events import MarketDataEvent
from eventmm.backtest.fees import FeeModel
from eventmm.backtest.fills import FillSimulator
from eventmm.backtest.metrics import compute_backtest_metrics
from eventmm.backtest.portfolio import Portfolio
from eventmm.backtest.reports import write_backtest_report
from eventmm.backtest.strategy import ThresholdSignalTaker


def run_threshold_backtest(
    config: dict, data_dir: Path = Path("data/processed/datasets")
) -> Path:
    dataset = config["dataset"]
    run_name = config.get("run_name", "weather_threshold_v1")
    df = load_backtest_dataset(dataset, data_dir=data_dir).sort("as_of_ts")

    strategy_cfg = config.get("strategy", {})
    strategy = ThresholdSignalTaker(
        min_edge_cents=float(strategy_cfg.get("min_edge_cents", 5)),
        quantity=int(strategy_cfg.get("quantity", 1)),
    )
    fee_cfg = config.get("fees", {})
    fee_model = FeeModel(
        fixed_fee_cents_per_contract=float(
            fee_cfg.get("fixed_fee_cents_per_contract", 0.1)
        ),
        include_fees=bool(fee_cfg.get("include_fees", True)),
    )
    fill_sim = FillSimulator(fee_model)
    portfolio = Portfolio()
    orders = []
    fills = []

    for row in df.to_dicts():
        if row.get("label") is None:
            continue
        event = MarketDataEvent(
            ts=row["as_of_ts"],
            market_ticker=row["market_ticker"],
            best_yes_bid=row.get("best_yes_bid"),
            best_yes_ask=row.get("best_yes_ask"),
            market_mid=row.get("market_mid"),
            market_microprice=row.get("market_microprice"),
            spread=row.get("market_spread"),
            depth_imbalance=row.get("market_depth_imbalance"),
        )
        for order in strategy.on_market_data(event, row):
            orders.append(order)
            fill = fill_sim.simulate_taker_fill(order, event)
            if fill:
                fills.append(fill)
                portfolio.apply_fill(fill)

    labels = {
        row["market_ticker"]: int(row["label"])
        for row in df.drop_nulls(["label"])
        .select(["market_ticker", "label"])
        .unique()
        .to_dicts()
    }
    for market_ticker, label in labels.items():
        portfolio.settle(market_ticker, label)

    metrics = compute_backtest_metrics(orders, fills, portfolio)
    out_dir = Path("artifacts") / "backtests" / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.yaml").write_text(json.dumps(config, indent=2, sort_keys=True))
    pl.DataFrame([asdict(order) for order in orders]).write_parquet(
        out_dir / "orders.parquet"
    )
    pl.DataFrame([fill.to_row() for fill in fills]).write_parquet(
        out_dir / "fills.parquet"
    )
    pl.DataFrame(portfolio.positions_rows()).write_parquet(
        out_dir / "positions.parquet"
    )
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True))
    write_backtest_report(out_dir / "report.md", metrics)
    return out_dir

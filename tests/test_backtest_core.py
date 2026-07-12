from datetime import datetime

from eventmm.backtest.events import MarketDataEvent, OrderEvent
from eventmm.backtest.fees import FeeModel
from eventmm.backtest.fills import FillSimulator
from eventmm.backtest.portfolio import Portfolio
from eventmm.backtest.risk import ExposureLimits, signed_yes_equivalent
from eventmm.backtest.strategy import ThresholdSignalTaker


def test_taker_buy_yes_fills_at_ask():
    order = OrderEvent(
        ts=datetime(2026, 1, 1),
        market_ticker="TEST",
        side="yes",
        action="buy",
        order_type="marketable_limit",
        price_cents=45,
        quantity=1,
    )
    market = MarketDataEvent(
        ts=order.ts,
        market_ticker="TEST",
        best_yes_bid=40,
        best_yes_ask=44,
        market_mid=42,
        market_microprice=42,
        spread=4,
        depth_imbalance=0,
    )

    fill = FillSimulator(
        FeeModel(fixed_fee_cents_per_contract=0.1)
    ).simulate_taker_fill(order, market)

    assert fill is not None
    assert fill.price_cents == 44
    assert fill.fee_cents == 0.1


def test_yes_buy_settlement_pnl_win_and_loss():
    portfolio = Portfolio()
    fill = FillSimulator(FeeModel(fixed_fee_cents_per_contract=0))._fill(
        OrderEvent(
            ts=datetime(2026, 1, 1),
            market_ticker="TEST",
            side="yes",
            action="buy",
            order_type="marketable_limit",
            price_cents=40,
            quantity=1,
        ),
        40,
        "taker",
    )
    portfolio.apply_fill(fill)

    assert portfolio.settle("TEST", 1) == 60
    assert portfolio.settle("TEST", 0) == -40


def test_sell_yes_settlement_pnl():
    portfolio = Portfolio()
    fill = FillSimulator(FeeModel(fixed_fee_cents_per_contract=0))._fill(
        OrderEvent(
            ts=datetime(2026, 1, 1),
            market_ticker="TEST",
            side="yes",
            action="sell",
            order_type="marketable_limit",
            price_cents=40,
            quantity=1,
        ),
        40,
        "taker",
    )
    portfolio.apply_fill(fill)

    assert portfolio.settle("TEST", 0) == 40
    assert portfolio.settle("TEST", 1) == -60


def test_threshold_signal_taker_uses_contract_aware_forecast_event():
    market = MarketDataEvent(
        ts=datetime(2026, 1, 1),
        market_ticker="TEST",
        best_yes_bid=1,
        best_yes_ask=2,
        market_mid=1.5,
        market_microprice=1.5,
        spread=1,
        depth_imbalance=0,
    )

    orders = ThresholdSignalTaker(min_edge_cents=5).on_market_data(
        market,
        {
            "forecast_above_threshold": 0,
            "forecast_event_indicator": 1,
        },
    )

    assert orders
    assert orders[0].action == "buy"
    assert orders[0].side == "yes"


def test_taker_fill_is_limited_by_available_depth():
    order = OrderEvent(
        ts=datetime(2026, 1, 1),
        market_ticker="TEST",
        side="yes",
        action="buy",
        order_type="marketable_limit",
        price_cents=45,
        quantity=5,
    )
    market = MarketDataEvent(
        ts=order.ts,
        market_ticker="TEST",
        best_yes_bid=40,
        best_yes_ask=44,
        market_mid=42,
        market_microprice=42,
        spread=4,
        depth_imbalance=0,
        yes_ask_depth=2,
    )
    fill = FillSimulator(FeeModel(include_fees=False)).simulate_taker_fill(
        order, market
    )
    assert fill is not None
    assert fill.quantity == 2


def test_kalshi_fee_formula_and_event_limits():
    fees = FeeModel()
    assert fees.estimate_fee_cents(50, 1, "taker") == 2.0
    assert fees.estimate_fee_cents(50, 100, "taker") == 175.0
    assert fees.estimate_fee_cents(50, 1, "maker") == 0.0

    limits = ExposureLimits(max_market_position=2, max_event_exposure=3)
    assert limits.allows(market_ticker="M1", event_ticker="E1", signed_quantity=2)
    limits.record(market_ticker="M1", event_ticker="E1", signed_quantity=2)
    assert not limits.allows(market_ticker="M1", event_ticker="E1", signed_quantity=1)
    assert limits.allows(market_ticker="M2", event_ticker="E1", signed_quantity=1)
    limits.record(market_ticker="M2", event_ticker="E1", signed_quantity=1)
    assert not limits.allows(market_ticker="M3", event_ticker="E1", signed_quantity=1)
    assert signed_yes_equivalent(side="yes", action="buy", quantity=2) == 2
    assert signed_yes_equivalent(side="no", action="buy", quantity=2) == -2

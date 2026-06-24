from datetime import datetime

from eventmm.backtest.events import MarketDataEvent, OrderEvent
from eventmm.backtest.fees import FeeModel
from eventmm.backtest.fills import FillSimulator
from eventmm.backtest.portfolio import Portfolio


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

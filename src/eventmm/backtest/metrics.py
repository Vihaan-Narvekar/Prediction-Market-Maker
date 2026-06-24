from eventmm.backtest.events import FillEvent, OrderEvent
from eventmm.backtest.portfolio import Portfolio


def compute_backtest_metrics(
    orders: list[OrderEvent],
    fills: list[FillEvent],
    portfolio: Portfolio,
) -> dict[str, float | int]:
    total_fees = sum(fill.fee_cents for fill in fills)
    gross_pnl = sum(
        position.realized_pnl_cents + position.fees_paid_cents
        for position in portfolio.positions.values()
    )
    net_pnl = sum(
        position.realized_pnl_cents for position in portfolio.positions.values()
    )
    return {
        "number_of_markets": len(portfolio.positions),
        "number_of_orders": len(orders),
        "number_of_fills": len(fills),
        "fill_rate": len(fills) / len(orders) if orders else 0.0,
        "average_fill_price": sum(fill.price_cents for fill in fills) / len(fills)
        if fills
        else 0.0,
        "total_fees": total_fees,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "pnl_per_contract": net_pnl / sum(fill.quantity for fill in fills)
        if fills
        else 0.0,
        "win_rate": sum(
            1
            for position in portfolio.positions.values()
            if position.realized_pnl_cents > 0
        )
        / len(portfolio.positions)
        if portfolio.positions
        else 0.0,
    }

from eventmm.backtest.events import FillEvent, MarketDataEvent, OrderEvent
from eventmm.backtest.fees import FeeModel


class FillSimulator:
    def __init__(self, fee_model: FeeModel):
        self.fee_model = fee_model

    def simulate_taker_fill(
        self,
        order: OrderEvent,
        market: MarketDataEvent,
    ) -> FillEvent | None:
        executable_price = self._executable_price(order, market)
        if executable_price is None:
            return None
        if order.action == "buy" and executable_price <= order.price_cents:
            return self._fill(order, executable_price, "taker")
        if order.action == "sell" and executable_price >= order.price_cents:
            return self._fill(order, executable_price, "taker")
        return None

    def _executable_price(
        self, order: OrderEvent, market: MarketDataEvent
    ) -> float | None:
        if order.side == "yes" and order.action == "buy":
            return market.best_yes_ask
        if order.side == "yes" and order.action == "sell":
            return market.best_yes_bid
        if (
            order.side == "no"
            and order.action == "buy"
            and market.best_yes_bid is not None
        ):
            return 100 - market.best_yes_bid
        if (
            order.side == "no"
            and order.action == "sell"
            and market.best_yes_ask is not None
        ):
            return 100 - market.best_yes_ask
        return None

    def _fill(self, order: OrderEvent, price_cents: float, liquidity: str) -> FillEvent:
        return FillEvent(
            ts=order.ts,
            market_ticker=order.market_ticker,
            side=order.side,
            action=order.action,
            price_cents=price_cents,
            quantity=order.quantity,
            fee_cents=self.fee_model.estimate_fee_cents(
                price_cents, order.quantity, liquidity
            ),
            liquidity=liquidity,
        )

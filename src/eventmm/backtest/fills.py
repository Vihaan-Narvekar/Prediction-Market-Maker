from typing import Literal

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
        available_depth = self._available_depth(order, market)
        if available_depth is not None and available_depth <= 0:
            return None
        if order.action == "buy" and executable_price <= order.price_cents:
            return self._fill(order, executable_price, "taker", available_depth)
        if order.action == "sell" and executable_price >= order.price_cents:
            return self._fill(order, executable_price, "taker", available_depth)
        return None

    def _available_depth(
        self, order: OrderEvent, market: MarketDataEvent
    ) -> int | None:
        if order.side == "yes" and order.action == "buy":
            return market.yes_ask_depth
        if order.side == "yes" and order.action == "sell":
            return market.yes_bid_depth
        if order.side == "no" and order.action == "buy":
            return market.no_ask_depth
        return market.no_bid_depth

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

    def _fill(
        self,
        order: OrderEvent,
        price_cents: float,
        liquidity: Literal["taker", "maker", "simulated"],
        available_quantity: int | None = None,
    ) -> FillEvent:
        quantity = (
            min(order.quantity, available_quantity)
            if available_quantity is not None
            else order.quantity
        )
        if quantity <= 0:
            raise ValueError("Fill quantity must be positive.")
        return FillEvent(
            ts=order.ts,
            market_ticker=order.market_ticker,
            side=order.side,
            action=order.action,
            price_cents=price_cents,
            quantity=quantity,
            fee_cents=self.fee_model.estimate_fee_cents(
                price_cents, quantity, liquidity
            ),
            liquidity=liquidity,
            requested_quantity=order.quantity,
            depth_source="known" if available_quantity is not None else "assumed",
        )

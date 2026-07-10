from dataclasses import dataclass

from eventmm.backtest.events import MarketDataEvent, OrderEvent, SignalEvent


class Strategy:
    def on_market_data(self, event: MarketDataEvent, row: dict) -> list[OrderEvent]:
        raise NotImplementedError


@dataclass
class ThresholdSignalTaker(Strategy):
    min_edge_cents: float = 5.0
    quantity: int = 1

    def on_market_data(self, event: MarketDataEvent, row: dict) -> list[OrderEvent]:
        p_yes = row.get("p_model")
        if p_yes is None:
            p_yes = row.get("forecast_event_indicator")
        if p_yes is None:
            p_yes = row.get("forecast_above_threshold")
        if p_yes is None:
            p_yes = (row.get("market_mid") or 50) / 100
        fair_value = 100 * float(p_yes)

        signal = SignalEvent(
            ts=event.ts,
            market_ticker=event.market_ticker,
            p_yes=float(p_yes),
            fair_value_cents=fair_value,
            edge_to_mid=fair_value - (event.market_mid or fair_value),
            buy_yes_edge=fair_value - event.best_yes_ask
            if event.best_yes_ask is not None
            else None,
            sell_yes_edge=event.best_yes_bid - fair_value
            if event.best_yes_bid is not None
            else None,
        )

        orders: list[OrderEvent] = []
        if (
            signal.buy_yes_edge is not None
            and signal.buy_yes_edge >= self.min_edge_cents
            and event.best_yes_ask is not None
        ):
            orders.append(
                OrderEvent(
                    ts=event.ts,
                    market_ticker=event.market_ticker,
                    side="yes",
                    action="buy",
                    order_type="marketable_limit",
                    price_cents=event.best_yes_ask,
                    quantity=self.quantity,
                )
            )
        if (
            signal.sell_yes_edge is not None
            and signal.sell_yes_edge >= self.min_edge_cents
            and event.best_yes_bid is not None
        ):
            orders.append(
                OrderEvent(
                    ts=event.ts,
                    market_ticker=event.market_ticker,
                    side="yes",
                    action="sell",
                    order_type="marketable_limit",
                    price_cents=event.best_yes_bid,
                    quantity=self.quantity,
                )
            )
        return orders

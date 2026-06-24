from dataclasses import dataclass, field

from eventmm.backtest.events import FillEvent


@dataclass
class Position:
    yes_position: int = 0
    no_position: int = 0
    yes_cash_flow_cents: float = 0.0
    no_cash_flow_cents: float = 0.0
    fees_paid_cents: float = 0.0
    realized_pnl_cents: float = 0.0


@dataclass
class Portfolio:
    positions: dict[str, Position] = field(default_factory=dict)

    def apply_fill(self, fill: FillEvent) -> None:
        pos = self.positions.setdefault(fill.market_ticker, Position())
        signed_qty = fill.quantity if fill.action == "buy" else -fill.quantity
        cash_flow = fill.price_cents * fill.quantity
        if fill.side == "yes":
            pos.yes_position += signed_qty
            pos.yes_cash_flow_cents += cash_flow if fill.action == "buy" else -cash_flow
        else:
            pos.no_position += signed_qty
            pos.no_cash_flow_cents += cash_flow if fill.action == "buy" else -cash_flow
        pos.fees_paid_cents += fill.fee_cents

    def settle(self, market_ticker: str, label: int) -> float:
        pos = self.positions.get(market_ticker)
        if pos is None:
            return 0.0
        yes_settlement = 100 * pos.yes_position * label
        no_settlement = 100 * pos.no_position * (1 - label)
        pnl = (
            yes_settlement
            + no_settlement
            - pos.yes_cash_flow_cents
            - pos.no_cash_flow_cents
            - pos.fees_paid_cents
        )
        pos.realized_pnl_cents = pnl
        return pnl

    def positions_rows(self) -> list[dict]:
        rows = []
        for market_ticker, pos in self.positions.items():
            rows.append(
                {
                    "market_ticker": market_ticker,
                    "yes_position": pos.yes_position,
                    "no_position": pos.no_position,
                    "yes_cash_flow_cents": pos.yes_cash_flow_cents,
                    "no_cash_flow_cents": pos.no_cash_flow_cents,
                    "fees_paid_cents": pos.fees_paid_cents,
                    "realized_pnl_cents": pos.realized_pnl_cents,
                }
            )
        return rows

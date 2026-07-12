from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING


@dataclass(frozen=True)
class FeeModel:
    include_fees: bool = True
    taker_rate: Decimal = Decimal("0.07")
    maker_rate: Decimal = Decimal("0.0175")
    multiplier: Decimal = Decimal("1")
    maker_multiplier: Decimal = Decimal("0")
    fixed_fee_cents_per_contract: float | None = None

    def estimate_fee_cents(
        self, price_cents: float, quantity: int, liquidity: str
    ) -> float:
        if not self.include_fees:
            return 0.0
        if self.fixed_fee_cents_per_contract is not None:
            return self.fixed_fee_cents_per_contract * quantity
        price = Decimal(str(price_cents)) / Decimal("100")
        rate = self.maker_rate if liquidity == "maker" else self.taker_rate
        multiplier = self.maker_multiplier if liquidity == "maker" else self.multiplier
        fee_dollars = (
            multiplier * rate * Decimal(quantity) * price * (Decimal("1") - price)
        )
        fee_dollars = fee_dollars.quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        order_fee_dollars = fee_dollars.quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        return float(order_fee_dollars * Decimal("100"))

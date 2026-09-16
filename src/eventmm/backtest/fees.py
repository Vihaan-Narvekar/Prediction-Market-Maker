from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from eventmm.utils.decimal import DecimalInput, to_decimal


@dataclass(frozen=True)
class FeeModel:
    include_fees: bool = True
    taker_rate: Decimal = Decimal("0.07")
    maker_rate: Decimal = Decimal("0.0175")
    multiplier: Decimal = Decimal("1")
    maker_multiplier: Decimal = Decimal("0")
    fixed_fee_cents_per_contract: Decimal | None = None

    def __post_init__(self) -> None:
        for name in (
            "taker_rate",
            "maker_rate",
            "multiplier",
            "maker_multiplier",
            "fixed_fee_cents_per_contract",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value))

    def estimate_fee_cents(
        self, price_cents: DecimalInput, quantity: DecimalInput, liquidity: str
    ) -> Decimal:
        price_cents = to_decimal(price_cents)
        quantity = to_decimal(quantity)
        if not 0 <= price_cents <= 100 or quantity < 0:
            raise ValueError("Invalid fee price or quantity")
        if not self.include_fees:
            return Decimal("0")
        if self.fixed_fee_cents_per_contract is not None:
            return to_decimal(self.fixed_fee_cents_per_contract) * quantity
        price = Decimal(str(price_cents)) / Decimal("100")
        rate = self.maker_rate if liquidity == "maker" else self.taker_rate
        multiplier = self.maker_multiplier if liquidity == "maker" else self.multiplier
        fee_dollars = (
            to_decimal(multiplier)
            * to_decimal(rate)
            * quantity
            * price
            * (Decimal("1") - price)
        )
        fee_dollars = fee_dollars.quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        order_fee_dollars = fee_dollars.quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        return order_fee_dollars * Decimal("100")

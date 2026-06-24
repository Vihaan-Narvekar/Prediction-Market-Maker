from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    fixed_fee_cents_per_contract: float = 0.1
    include_fees: bool = True

    def estimate_fee_cents(
        self, price_cents: float, quantity: int, liquidity: str
    ) -> float:
        if not self.include_fees:
            return 0.0
        return self.fixed_fee_cents_per_contract * quantity

class SequenceGapError(Exception):
    def __init__(self, market_ticker: str, expected: int, received: int):
        self.market_ticker = market_ticker
        self.expected = expected
        self.received = received
        super().__init__(
            f"Sequence gap for {market_ticker}: expected={expected}, received={received}"
        )

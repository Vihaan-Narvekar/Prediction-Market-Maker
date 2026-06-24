from decimal import Decimal

from eventmm.data_sources.base import SYNTHETIC_PROFILE
from eventmm.lob.book import BinaryOrderBook

PROFILE = SYNTHETIC_PROFILE


def make_synthetic_book(
    market_ticker: str = "TEST",
    yes_bid: int = 48,
    yes_ask: int = 52,
    bid_qty: int = 100,
    ask_qty: int = 120,
) -> BinaryOrderBook:
    no_bid = 100 - yes_ask
    book = BinaryOrderBook(
        market_ticker=market_ticker,
        yes_bids={yes_bid: Decimal(str(bid_qty))},
        no_bids={no_bid: Decimal(str(ask_qty))},
    )
    book.validate()
    return book

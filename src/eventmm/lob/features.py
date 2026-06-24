from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from eventmm.lob.book import BinaryOrderBook
from eventmm.lob.validation import classify_book_quality


@dataclass(frozen=True)
class BookFeatures:
    market_ticker: str
    environment: str
    ts: datetime | None
    best_yes_bid: int | None
    best_yes_ask: int | None
    best_no_bid: int | None
    best_no_ask: int | None
    yes_spread: int | None
    yes_midpoint: float | None
    yes_microprice: float | None
    yes_bid_depth_1: float | None
    yes_ask_depth_1: float | None
    imbalance_1: float | None
    imbalance_3: float | None
    book_is_crossed: bool
    book_is_locked: bool
    book_quality_flag: str
    missing_reason: str | None


def _top_bid_depth(book_side: dict[int, Decimal], levels: int) -> Decimal:
    prices = sorted(book_side, reverse=True)[:levels]
    return sum((book_side[price] for price in prices), Decimal("0"))


def _top_ask_depth(book_side: dict[int, Decimal], levels: int) -> Decimal:
    prices = sorted(book_side)[:levels]
    return sum((book_side[price] for price in prices), Decimal("0"))


def _imbalance(bid_depth: Decimal, ask_depth: Decimal) -> float | None:
    denominator = bid_depth + ask_depth
    if denominator == 0:
        return None
    return float((bid_depth - ask_depth) / denominator)


def compute_features(
    book: BinaryOrderBook, *, environment: str = "prod_public"
) -> BookFeatures:
    bid = book.best_yes_bid()
    ask = book.best_yes_ask()
    yes_asks = book.yes_asks()

    bid_depth_1 = book.yes_bids.get(bid, Decimal("0")) if bid is not None else None
    ask_depth_1 = yes_asks.get(ask, Decimal("0")) if ask is not None else None

    microprice = None
    if (
        bid is not None
        and ask is not None
        and bid_depth_1 is not None
        and ask_depth_1 is not None
    ):
        denominator = bid_depth_1 + ask_depth_1
        if denominator > 0:
            microprice = float(
                (Decimal(ask) * bid_depth_1 + Decimal(bid) * ask_depth_1) / denominator
            )

    bid_depth_3 = _top_bid_depth(book.yes_bids, 3)
    ask_depth_3 = _top_ask_depth(yes_asks, 3)
    spread = book.yes_spread()
    quality_flag, missing_reason = classify_book_quality(book, environment=environment)

    return BookFeatures(
        market_ticker=book.market_ticker,
        environment=environment,
        ts=book.last_update_ts,
        best_yes_bid=bid,
        best_yes_ask=ask,
        best_no_bid=book.best_no_bid(),
        best_no_ask=book.best_no_ask(),
        yes_spread=spread,
        yes_midpoint=book.yes_midpoint(),
        yes_microprice=microprice,
        yes_bid_depth_1=float(bid_depth_1) if bid_depth_1 is not None else None,
        yes_ask_depth_1=float(ask_depth_1) if ask_depth_1 is not None else None,
        imbalance_1=_imbalance(
            bid_depth_1 or Decimal("0"), ask_depth_1 or Decimal("0")
        ),
        imbalance_3=_imbalance(bid_depth_3, ask_depth_3),
        book_is_crossed=spread is not None and spread < 0,
        book_is_locked=spread == 0,
        book_quality_flag=quality_flag.value,
        missing_reason=missing_reason,
    )

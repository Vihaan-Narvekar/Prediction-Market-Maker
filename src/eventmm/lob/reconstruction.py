from datetime import datetime
from decimal import Decimal

import structlog

from eventmm.lob.book import BinaryOrderBook
from eventmm.lob.exceptions import SequenceGapError

logger = structlog.get_logger()


class OrderBookManager:
    def __init__(self):
        self.books: dict[str, BinaryOrderBook] = {}

    def get_book(self, market_ticker: str) -> BinaryOrderBook:
        if market_ticker not in self.books:
            self.books[market_ticker] = BinaryOrderBook(market_ticker)
        return self.books[market_ticker]

    def apply_snapshot(
        self,
        market_ticker: str,
        yes_bids: dict[int, Decimal],
        no_bids: dict[int, Decimal],
        seq: int | None = None,
        ts: datetime | None = None,
    ) -> BinaryOrderBook:
        book = self.get_book(market_ticker)
        book.apply_snapshot(yes_bids=yes_bids, no_bids=no_bids, seq=seq, ts=ts)
        logger.info(
            "snapshot_applied",
            market_ticker=market_ticker,
            seq=seq,
            yes_levels=len(yes_bids),
            no_levels=len(no_bids),
        )
        return book

    def apply_delta(
        self,
        market_ticker: str,
        side: str,
        price_cents: int,
        delta_qty: Decimal,
        seq: int,
        ts: datetime | None = None,
    ) -> BinaryOrderBook:
        book = self.get_book(market_ticker)

        if book.last_seq is not None and seq != book.last_seq + 1:
            logger.warning(
                "sequence_gap_detected",
                market_ticker=market_ticker,
                expected=book.last_seq + 1,
                received=seq,
            )
            raise SequenceGapError(market_ticker, book.last_seq + 1, seq)

        book.apply_delta(
            side=side,
            price_cents=price_cents,
            delta_qty=delta_qty,
            seq=seq,
            ts=ts,
        )
        logger.info(
            "delta_applied",
            market_ticker=market_ticker,
            side=side,
            price_cents=price_cents,
            delta_qty=str(delta_qty),
            seq=seq,
        )
        return book

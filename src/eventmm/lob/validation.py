from enum import Enum

from eventmm.lob.book import BinaryOrderBook


class BookQualityFlag(str, Enum):
    VALID_TWO_SIDED = "VALID_TWO_SIDED"
    ONE_SIDED_YES_ONLY = "ONE_SIDED_YES_ONLY"
    ONE_SIDED_NO_ONLY = "ONE_SIDED_NO_ONLY"
    EMPTY_BOOK = "EMPTY_BOOK"
    LOCKED_BOOK = "LOCKED_BOOK"
    CROSSED_BOOK = "CROSSED_BOOK"
    DEMO_ARTIFICIAL = "DEMO_ARTIFICIAL"


def classify_book_quality(
    book: BinaryOrderBook,
    *,
    environment: str,
) -> tuple[BookQualityFlag, str | None]:
    if environment == "demo":
        return (
            BookQualityFlag.DEMO_ARTIFICIAL,
            "Demo data is for integration testing and is not research-representative.",
        )

    bid = book.best_yes_bid()
    ask = book.best_yes_ask()

    if bid is None and ask is None:
        return (
            BookQualityFlag.EMPTY_BOOK,
            "Cannot compute metrics because both sides are empty.",
        )
    if bid is not None and ask is None:
        return (
            BookQualityFlag.ONE_SIDED_YES_ONLY,
            "Cannot infer Yes ask because the No bid book is empty.",
        )
    if bid is None and ask is not None:
        return (
            BookQualityFlag.ONE_SIDED_NO_ONLY,
            "Cannot compute Yes bid because the Yes bid book is empty.",
        )
    if bid is not None and ask is not None and bid > ask:
        return (
            BookQualityFlag.CROSSED_BOOK,
            "Best Yes bid is greater than inferred Yes ask.",
        )
    if bid == ask:
        return BookQualityFlag.LOCKED_BOOK, None

    return BookQualityFlag.VALID_TWO_SIDED, None

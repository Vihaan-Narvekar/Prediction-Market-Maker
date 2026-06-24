from decimal import Decimal

import pytest

from eventmm.lob.book import BinaryOrderBook


def test_snapshot_sets_best_prices():
    book = BinaryOrderBook("TEST")
    book.apply_snapshot(
        yes_bids={40: Decimal("10")},
        no_bids={55: Decimal("20")},
        seq=1,
    )

    assert book.best_yes_bid() == 40
    assert book.best_yes_ask() == 45
    assert book.yes_spread() == 5


def test_delta_adds_level():
    book = BinaryOrderBook("TEST")
    book.apply_snapshot({40: Decimal("10")}, {55: Decimal("20")}, seq=1)
    book.apply_delta("yes", 41, Decimal("3"), seq=2)

    assert book.best_yes_bid() == 41


def test_delta_removes_level():
    book = BinaryOrderBook("TEST")
    book.apply_snapshot({40: Decimal("10")}, {55: Decimal("20")}, seq=1)
    book.apply_delta("yes", 40, Decimal("-10"), seq=2)

    assert 40 not in book.yes_bids


def test_crossed_book_raises():
    book = BinaryOrderBook("TEST")
    book.yes_bids = {70: Decimal("10")}
    book.no_bids = {40: Decimal("5")}

    with pytest.raises(ValueError):
        book.validate()

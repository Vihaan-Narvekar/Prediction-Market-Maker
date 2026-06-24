from decimal import Decimal

import pytest

from eventmm.lob.exceptions import SequenceGapError
from eventmm.lob.reconstruction import OrderBookManager


def test_manager_applies_snapshot_and_delta():
    manager = OrderBookManager()
    manager.apply_snapshot("TEST", {40: Decimal("10")}, {55: Decimal("20")}, seq=1)
    book = manager.apply_delta("TEST", "yes", 41, Decimal("2"), seq=2)

    assert book.best_yes_bid() == 41


def test_manager_raises_on_sequence_gap():
    manager = OrderBookManager()
    manager.apply_snapshot("TEST", {40: Decimal("10")}, {55: Decimal("20")}, seq=1)

    with pytest.raises(SequenceGapError):
        manager.apply_delta("TEST", "yes", 41, Decimal("2"), seq=3)

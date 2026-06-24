from decimal import Decimal

from eventmm.lob.book import BinaryOrderBook
from eventmm.lob.features import compute_features
from eventmm.data_sources.synthetic import make_synthetic_book


def test_microprice_moves_toward_ask_when_bid_depth_large():
    book = BinaryOrderBook("TEST")
    book.apply_snapshot(
        yes_bids={40: Decimal("100")},
        no_bids={55: Decimal("10")},
        seq=1,
    )

    features = compute_features(book)

    assert features.yes_midpoint == 42.5
    assert features.yes_microprice is not None
    assert features.yes_microprice > features.yes_midpoint
    assert features.environment == "prod_public"
    assert features.book_quality_flag == "VALID_TWO_SIDED"


def test_demo_features_are_flagged_as_artificial():
    book = make_synthetic_book()

    features = compute_features(book, environment="demo")

    assert features.book_quality_flag == "DEMO_ARTIFICIAL"
    assert features.missing_reason is not None


def test_one_sided_book_has_missing_reason():
    book = BinaryOrderBook("TEST")
    book.apply_snapshot(yes_bids={48: Decimal("100")}, no_bids={})

    features = compute_features(book)

    assert features.yes_spread is None
    assert features.book_quality_flag == "ONE_SIDED_YES_ONLY"
    assert features.missing_reason is not None

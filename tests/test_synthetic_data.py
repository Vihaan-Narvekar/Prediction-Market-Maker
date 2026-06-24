from eventmm.data_sources.synthetic import make_synthetic_book
from eventmm.lob.features import compute_features


def test_make_synthetic_book_uses_no_bid_to_imply_yes_ask():
    book = make_synthetic_book(yes_bid=48, yes_ask=52, bid_qty=100, ask_qty=120)

    features = compute_features(book, environment="synthetic")

    assert book.best_no_bid() == 48
    assert features.best_yes_bid == 48
    assert features.best_yes_ask == 52
    assert features.yes_midpoint == 50

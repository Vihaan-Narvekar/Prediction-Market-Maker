from eventmm.datasets.labels import build_market_labels


def test_build_market_label_yes():
    labels = build_market_labels(
        [
            {
                "ticker": "TEST",
                "event_ticker": "EVENT",
                "series_ticker": "SERIES",
                "status": "settled",
                "result": "yes",
            }
        ]
    )

    assert labels[0]["label"] == 1
    assert labels[0]["label_quality"] == "from_kalshi_settlement"


def test_build_market_label_unsettled():
    labels = build_market_labels([{"ticker": "TEST", "status": "open"}])

    assert labels[0]["label"] is None
    assert labels[0]["label_quality"] == "unsettled"

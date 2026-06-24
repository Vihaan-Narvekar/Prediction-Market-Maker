from eventmm.contracts.settlement import build_market_label


def build_market_labels(markets: list[dict]) -> list[dict]:
    return [build_market_label(market) for market in markets]

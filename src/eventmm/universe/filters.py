def market_passes_filters(
    market: dict,
    *,
    min_volume: int = 100,
    min_open_interest: int = 100,
    max_spread_cents: int | None = None,
    exclude_keywords: list[str] | None = None,
) -> bool:
    exclude_keywords = exclude_keywords or []

    title = market.get("title", "").lower()

    if any(keyword.lower() in title for keyword in exclude_keywords):
        return False

    if market.get("volume", 0) < min_volume:
        return False

    if market.get("open_interest", 0) < min_open_interest:
        return False

    if market.get("status") != "open":
        return False

    return True

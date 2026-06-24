from eventmm.universe.filters import market_passes_filters
from eventmm.universe.market_loader import MarketLoader


class UniverseBuilder:
    def __init__(self, loader: MarketLoader):
        self.loader = loader

    async def build(
        self,
        *,
        series_ticker: str | None = None,
        min_volume: int = 100,
        min_open_interest: int = 100,
        exclude_keywords: list[str] | None = None,
        max_markets: int = 100,
    ) -> list[dict]:
        markets = await self.loader.load_all_open_markets(series_ticker=series_ticker)
        filtered = [
            market
            for market in markets
            if market_passes_filters(
                market,
                min_volume=min_volume,
                min_open_interest=min_open_interest,
                exclude_keywords=exclude_keywords,
            )
        ]
        return sorted(
            filtered,
            key=lambda market: (
                market.get("volume") or 0,
                market.get("open_interest") or 0,
            ),
            reverse=True,
        )[:max_markets]

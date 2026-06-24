class MarketLoader:
    def __init__(self, client):
        self.client = client

    async def load_all_open_markets(
        self, series_ticker: str | None = None
    ) -> list[dict]:
        markets = []
        cursor = None

        while True:
            data = await self.client.get_markets(
                status="open",
                series_ticker=series_ticker,
                limit=1000,
                cursor=cursor,
            )

            markets.extend(data.get("markets", []))
            cursor = data.get("cursor")

            if not cursor:
                break

        return markets

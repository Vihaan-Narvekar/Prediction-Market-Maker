from dataclasses import dataclass, field
from datetime import datetime
from statistics import median


@dataclass
class MarketDataQualityStats:
    market_ticker: str
    total_messages: int = 0
    snapshots: int = 0
    deltas: int = 0
    sequence_gaps: int = 0
    reconnects: int = 0
    crossed_books: int = 0
    locked_books: int = 0
    one_sided_books: int = 0
    valid_two_sided_books: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    last_message_ts: datetime | None = None

    def record_latency(self, latency_ms: float | None) -> None:
        if latency_ms is not None:
            self.latencies_ms.append(latency_ms)

    def latency_percentile(self, percentile: float) -> float | None:
        if not self.latencies_ms:
            return None
        values = sorted(self.latencies_ms)
        index = min(len(values) - 1, round((percentile / 100) * (len(values) - 1)))
        return values[index]

    def median_latency_ms(self) -> float | None:
        if not self.latencies_ms:
            return None
        return float(median(self.latencies_ms))

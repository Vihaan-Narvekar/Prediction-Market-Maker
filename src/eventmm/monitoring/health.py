from eventmm.monitoring.metrics import MarketDataQualityStats


def render_quality_report(stats: MarketDataQualityStats) -> str:
    return "\n".join(
        [
            f"# Market data quality: {stats.market_ticker}",
            "",
            "## Messages",
            f"- total messages: {stats.total_messages}",
            f"- snapshots: {stats.snapshots}",
            f"- deltas: {stats.deltas}",
            f"- sequence gaps: {stats.sequence_gaps}",
            f"- reconnects: {stats.reconnects}",
            "",
            "## Book validity",
            f"- valid two-sided books: {stats.valid_two_sided_books}",
            f"- one-sided books: {stats.one_sided_books}",
            f"- locked books: {stats.locked_books}",
            f"- crossed books: {stats.crossed_books}",
            "",
            "## Latency",
            f"- median: {stats.median_latency_ms()} ms",
            f"- p95: {stats.latency_percentile(95)} ms",
            f"- p99: {stats.latency_percentile(99)} ms",
        ]
    )

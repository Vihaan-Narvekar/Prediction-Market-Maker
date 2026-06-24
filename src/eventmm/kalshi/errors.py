class KalshiClientError(Exception):
    """Base exception for Kalshi client errors."""


class KalshiRateLimitError(KalshiClientError):
    """Raised when Kalshi responds with HTTP 429."""

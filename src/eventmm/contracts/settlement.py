from datetime import datetime, timezone
from typing import Any


def extract_market_result(market: dict[str, Any]) -> str | None:
    for key in ("result", "settlement_value", "resolved_outcome", "winning_side"):
        value = market.get(key)
        if value is not None:
            normalized = str(value).upper()
            if normalized in {"YES", "Y", "TRUE", "1"}:
                return "YES"
            if normalized in {"NO", "N", "FALSE", "0"}:
                return "NO"
    return None


def label_from_result(result: str | None) -> int | None:
    if result == "YES":
        return 1
    if result == "NO":
        return 0
    return None


def build_market_label(market: dict[str, Any]) -> dict[str, Any]:
    result = extract_market_result(market)
    label = label_from_result(result)
    status = str(market.get("status") or "").lower()

    if label is None and status not in {"settled", "closed", "finalized"}:
        quality = "unsettled"
        confidence = "LOW"
    elif label is None:
        quality = "missing_result"
        confidence = "LOW"
    else:
        quality = "from_kalshi_settlement"
        confidence = "MEDIUM"

    return {
        "market_ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
        "expiration_time": market.get("expiration_time"),
        "settlement_time": market.get("settlement_timer") or market.get("settled_time"),
        "result": result,
        "label": label,
        "label_source": "kalshi_market",
        "label_quality": quality,
        "label_confidence": confidence,
        "settlement_rule_match": None,
        "observed_source": None,
        "observed_station": None,
        "observed_value": None,
        "kalshi_result": result,
        "observed_result": None,
        "label_disagreement_flag": None,
        "created_ts": datetime.now(timezone.utc).isoformat(),
    }

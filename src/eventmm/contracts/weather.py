import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class WeatherContractSpec:
    market_ticker: str
    location: str | None
    metric: str | None
    contract_date: date | None
    threshold_value: float | None
    threshold_unit: str | None
    comparison_operator: str | None
    parse_status: str
    parse_error: str | None = None
    threshold_upper_value: float | None = None
    parse_source: str = "regex"
    contract_type: str = "threshold"
    settlement_station: str | None = None

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["contract_date"] = (
            self.contract_date.isoformat() if self.contract_date else None
        )
        return row


LOCATION_ALIASES = {
    "NYC": "NYC",
    "NEW YORK": "NYC",
    "NEW YORK CITY": "NYC",
    "CHICAGO": "CHICAGO",
    "MIAMI": "MIAMI",
    "AUSTIN": "AUSTIN",
    "BOSTON": "BOSTON",
}

TEMP_RANGE_RE = re.compile(
    r"(?P<location>NYC|New York City|New York|Chicago|Miami|Austin|Boston)"
    r".*?(?P<low>-?\d+(?:\.\d+)?)\s?-\s?(?P<high>-?\d+(?:\.\d+)?)"
    r"\s?(?:°\s?F?|F|degrees?)?",
    re.IGNORECASE,
)

TEMP_THRESHOLD_RE = re.compile(
    r"(?P<location>NYC|New York City|New York|Chicago|Miami|Austin|Boston)"
    r".*?(?P<symbol>[<>])?\s?"
    r".*?(?P<operator>above|over|at least|below|under|less than|greater than)?"
    r".*?(?P<threshold>-?\d+(?:\.\d+)?)\s?(?:°\s?F?|F|degrees?)?",
    re.IGNORECASE,
)

TITLE_DATE_RE = re.compile(
    r"on\s+(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2}),\s*(?P<year>\d{4})",
    re.IGNORECASE,
)


def parse_date_from_market(market: dict[str, Any]) -> date | None:
    for key in (
        "settlement_timer",
        "close_time",
        "expiration_time",
        "expected_expiration_time",
    ):
        value = market.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            continue

    ticker = str(market.get("ticker", ""))
    match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ticker)
    if not match:
        return None

    day, month_name, year = match.groups()
    try:
        return datetime.strptime(f"20{year}-{month_name}-{day}", "%Y-%b-%d").date()
    except ValueError:
        return None


def parse_date_from_title(title: str) -> date | None:
    match = TITLE_DATE_RE.search(title)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group('year')}-{match.group('month')}-{match.group('day')}",
            "%Y-%b-%d",
        ).date()
    except ValueError:
        return None


def _normalize_operator(operator: str | None) -> str:
    if not operator:
        return ">"
    normalized = operator.lower()
    if normalized in {"above", "over", "greater than", "at least"}:
        return ">"
    if normalized in {"below", "under", "less than"}:
        return "<"
    return ">"


def _normalize_symbol_or_operator(symbol: str | None, operator: str | None) -> str:
    if symbol in {">", "<"}:
        return symbol
    return _normalize_operator(operator)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _spec_from_override(ticker: str, override: dict[str, Any]) -> WeatherContractSpec:
    threshold_low = override.get("threshold_low", override.get("threshold_value"))
    threshold_high = override.get(
        "threshold_high", override.get("threshold_upper_value")
    )
    return WeatherContractSpec(
        market_ticker=ticker,
        location=override.get("location"),
        metric=override.get("metric", "daily_high_temperature"),
        contract_date=_parse_date(override.get("contract_date")),
        threshold_value=float(threshold_low) if threshold_low is not None else None,
        threshold_unit=override.get("threshold_unit", "F"),
        comparison_operator=override.get("comparison_operator"),
        parse_status="parsed",
        threshold_upper_value=float(threshold_high)
        if threshold_high is not None
        else None,
        parse_source="override",
        contract_type=override.get("contract_type", "threshold"),
        settlement_station=override.get("settlement_station"),
    )


def parse_weather_contract(
    market: dict[str, Any],
    overrides: dict[str, dict[str, Any]] | None = None,
) -> WeatherContractSpec:
    ticker = str(market.get("ticker") or "")
    if overrides and ticker in overrides:
        return _spec_from_override(ticker, overrides[ticker])

    title = " ".join(
        str(market.get(key) or "")
        for key in ("title", "subtitle", "rules_primary", "rules_secondary")
    )

    if not ticker:
        return WeatherContractSpec(
            market_ticker=ticker,
            location=None,
            metric=None,
            contract_date=None,
            threshold_value=None,
            threshold_unit=None,
            comparison_operator=None,
            parse_status="failed",
            parse_error="missing ticker",
            parse_source="failed",
        )

    range_match = TEMP_RANGE_RE.search(title)
    if range_match:
        return WeatherContractSpec(
            market_ticker=ticker,
            location=LOCATION_ALIASES[range_match.group("location").upper()],
            metric="daily_high_temperature",
            contract_date=parse_date_from_title(title)
            or parse_date_from_market(market),
            threshold_value=float(range_match.group("low")),
            threshold_unit="F",
            comparison_operator="range",
            parse_status="parsed",
            threshold_upper_value=float(range_match.group("high")),
            contract_type="range",
        )

    match = TEMP_THRESHOLD_RE.search(title)
    if not match:
        return WeatherContractSpec(
            market_ticker=ticker,
            location=None,
            metric=None,
            contract_date=None,
            threshold_value=None,
            threshold_unit=None,
            comparison_operator=None,
            parse_status="failed",
            parse_error="unsupported weather title",
            parse_source="failed",
        )

    location = LOCATION_ALIASES[match.group("location").upper()]
    contract_date = parse_date_from_title(title) or parse_date_from_market(market)

    return WeatherContractSpec(
        market_ticker=ticker,
        location=location,
        metric="daily_high_temperature",
        contract_date=contract_date,
        threshold_value=float(match.group("threshold")),
        threshold_unit="F",
        comparison_operator=_normalize_symbol_or_operator(
            match.group("symbol"),
            match.group("operator"),
        ),
        parse_status="parsed",
    )


def parse_weather_contracts(
    markets: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[WeatherContractSpec]:
    return [parse_weather_contract(market, overrides=overrides) for market in markets]

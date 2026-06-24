from eventmm.contracts.weather import parse_weather_contract


def test_weather_contract_override():
    spec = parse_weather_contract(
        {"ticker": "KXHIGHNY-TEST", "title": "unparseable"},
        overrides={
            "KXHIGHNY-TEST": {
                "location": "NYC",
                "metric": "daily_high_temperature",
                "contract_date": "2026-06-23",
                "threshold_low": 85,
                "comparison_operator": ">=",
                "settlement_station": "KNYC",
            }
        },
    )

    assert spec.parse_status == "parsed"
    assert spec.parse_source == "override"
    assert spec.threshold_value == 85

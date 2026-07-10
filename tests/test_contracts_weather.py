from eventmm.contracts.weather import parse_weather_contract


def test_parse_weather_contract_title():
    spec = parse_weather_contract(
        {
            "ticker": "KXHIGHNY-26JUN26-T85",
            "title": "Will the high temperature in NYC be above 85°F on Jun 26?",
            "close_time": "2026-06-26T22:00:00Z",
        }
    )

    assert spec.parse_status == "parsed"
    assert spec.location == "NYC"
    assert spec.threshold_value == 85
    assert spec.threshold_unit == "F"
    assert spec.comparison_operator == ">"


def test_parse_weather_contract_less_than_symbol():
    spec = parse_weather_contract(
        {
            "ticker": "KXHIGHNY-26JUN29-T79",
            "title": "Will the high temp in NYC be <79° on Jun 29, 2026?",
            "close_time": "2026-06-29T22:00:00Z",
        }
    )

    assert spec.parse_status == "parsed"
    assert spec.threshold_value == 79
    assert spec.comparison_operator == "<"


def test_failed_weather_parse_is_reviewable():
    spec = parse_weather_contract({"ticker": "TEST", "title": "Will it rain?"})

    assert spec.parse_status == "failed"
    assert spec.parse_error

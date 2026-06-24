from eventmm.contracts.weather import WeatherContractSpec, parse_weather_contract


def parse_contract(market: dict) -> WeatherContractSpec:
    return parse_weather_contract(market)

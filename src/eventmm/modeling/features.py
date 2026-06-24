MARKET_ONLY = [
    "market_mid",
    "market_spread",
    "time_to_expiry_hours",
]

MICROSTRUCTURE = [
    "market_mid",
    "market_microprice",
    "market_spread",
    "market_depth_imbalance",
    "time_to_expiry_hours",
]

WEATHER_ONLY = [
    "forecast_minus_threshold",
    "abs_forecast_distance_to_threshold",
    "forecast_above_threshold",
    "time_to_expiry_hours",
]

WEATHER_MARKET = [
    "forecast_minus_threshold",
    "abs_forecast_distance_to_threshold",
    "forecast_above_threshold",
    "market_mid",
    "market_spread",
    "time_to_expiry_hours",
]

FULL = [
    "forecast_minus_threshold",
    "abs_forecast_distance_to_threshold",
    "forecast_above_threshold",
    "market_mid",
    "market_microprice",
    "market_spread",
    "market_depth_imbalance",
    "time_to_expiry_hours",
]

EDGE_DIAGNOSTICS = [
    "forecast_minus_threshold",
    "market_mid",
    "market_microprice",
    "microprice_minus_mid",
    "market_spread",
    "market_depth_imbalance",
    "time_to_expiry_hours",
]

FEATURE_SETS = {
    "market_only": MARKET_ONLY,
    "microstructure": MICROSTRUCTURE,
    "weather_only": WEATHER_ONLY,
    "weather_market": WEATHER_MARKET,
    "full": FULL,
    "edge_diagnostics": EDGE_DIAGNOSTICS,
}

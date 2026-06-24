import polars as pl

from eventmm.research.baselines import add_weather_baseline_features


def test_add_weather_baseline_features():
    df = pl.DataFrame(
        {
            "forecast_temperature": [86.0],
            "threshold_value": [85.0],
            "market_microprice": [63.0],
            "market_mid": [62.0],
        }
    )

    out = add_weather_baseline_features(df)

    assert out["forecast_minus_threshold"][0] == 1.0
    assert out["forecast_above_threshold"][0] == 1
    assert out["microprice_minus_mid"][0] == 1.0

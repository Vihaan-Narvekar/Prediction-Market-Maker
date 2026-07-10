import numpy as np
import polars as pl


def market_midpoint_probability(df: pl.DataFrame) -> np.ndarray:
    return (df["market_mid"].to_numpy() / 100).clip(0.001, 0.999)


def microprice_probability(df: pl.DataFrame) -> np.ndarray:
    return (df["market_microprice"].to_numpy() / 100).clip(0.001, 0.999)


def forecast_threshold_probability(df: pl.DataFrame) -> np.ndarray:
    column = (
        "forecast_event_indicator"
        if "forecast_event_indicator" in df.columns
        else "forecast_above_threshold"
    )
    return df[column].to_numpy().clip(0.001, 0.999)

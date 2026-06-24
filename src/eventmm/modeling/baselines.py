import numpy as np
import polars as pl


def market_midpoint_probability(df: pl.DataFrame) -> np.ndarray:
    return (df["market_mid"].to_numpy() / 100).clip(0.001, 0.999)


def microprice_probability(df: pl.DataFrame) -> np.ndarray:
    return (df["market_microprice"].to_numpy() / 100).clip(0.001, 0.999)


def forecast_threshold_probability(df: pl.DataFrame) -> np.ndarray:
    return df["forecast_above_threshold"].to_numpy().clip(0.001, 0.999)

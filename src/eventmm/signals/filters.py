import polars as pl


def filter_tradeable_edges(
    df: pl.DataFrame, min_abs_edge: float = 0.05
) -> pl.DataFrame:
    if "edge_mid" not in df.columns:
        return df
    return df.filter(pl.col("edge_mid").abs() >= min_abs_edge)

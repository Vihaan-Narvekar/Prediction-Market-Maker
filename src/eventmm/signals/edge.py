import polars as pl


def add_edge_columns(df: pl.DataFrame) -> pl.DataFrame:
    expressions = []
    if {"p_model", "market_mid"}.issubset(df.columns):
        expressions.append(
            (pl.col("p_model") - pl.col("market_mid") / 100).alias("edge_mid")
        )
    if {"p_model", "market_microprice"}.issubset(df.columns):
        expressions.append(
            (pl.col("p_model") - pl.col("market_microprice") / 100).alias(
                "edge_microprice"
            )
        )
    return df.with_columns(expressions) if expressions else df

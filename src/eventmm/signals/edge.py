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
    if {"p_model", "best_yes_ask"}.issubset(df.columns):
        expressions.append(
            (pl.col("p_model") * 100 - pl.col("best_yes_ask")).alias(
                "yes_edge_to_ask_cents"
            )
        )
    if {"p_model", "best_no_ask"}.issubset(df.columns):
        expressions.append(
            ((1 - pl.col("p_model")) * 100 - pl.col("best_no_ask")).alias(
                "no_edge_to_ask_cents"
            )
        )
    return df.with_columns(expressions) if expressions else df

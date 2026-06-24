import polars as pl


def attach_predictions(metadata: pl.DataFrame, p_model) -> pl.DataFrame:
    return metadata.with_columns(pl.Series("p_model", p_model))

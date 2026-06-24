import polars as pl


def temporal_split(
    df: pl.DataFrame,
    time_col: str,
    train_frac: float = 0.6,
    val_frac: float = 0.2,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    df = df.sort(time_col)
    n_rows = len(df)
    train_end = int(n_rows * train_frac)
    val_end = int(n_rows * (train_frac + val_frac))
    return df[:train_end], df[train_end:val_end], df[val_end:]


def contract_date_split(
    df: pl.DataFrame,
    date_col: str = "contract_date",
    train_frac: float = 0.6,
    val_frac: float = 0.2,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    dates = df.select(date_col).drop_nulls().unique().sort(date_col)[date_col].to_list()
    if not dates:
        return temporal_split(df, "as_of_ts", train_frac=train_frac, val_frac=val_frac)

    train_end = int(len(dates) * train_frac)
    val_end = int(len(dates) * (train_frac + val_frac))
    train_dates = set(dates[:train_end])
    val_dates = set(dates[train_end:val_end])

    train = df.filter(pl.col(date_col).is_in(train_dates))
    val = df.filter(pl.col(date_col).is_in(val_dates))
    test = df.filter(~pl.col(date_col).is_in(train_dates | val_dates))
    return train, val, test

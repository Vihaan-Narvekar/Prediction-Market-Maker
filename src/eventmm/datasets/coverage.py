import polars as pl


def compute_column_coverage(df: pl.DataFrame) -> pl.DataFrame:
    rows = len(df)
    if rows == 0:
        return pl.DataFrame(
            {
                "column": df.columns,
                "non_null": [0] * len(df.columns),
                "coverage_pct": [0.0] * len(df.columns),
            }
        )
    return pl.DataFrame(
        [
            {
                "column": column,
                "non_null": df.filter(pl.col(column).is_not_null()).height,
                "coverage_pct": 100
                * df.filter(pl.col(column).is_not_null()).height
                / rows,
            }
            for column in df.columns
        ]
    ).sort("coverage_pct")


def compute_feature_set_coverage(
    df: pl.DataFrame,
    feature_sets: dict[str, list[str]],
    label_col: str = "label",
) -> pl.DataFrame:
    rows = []
    for name, features in feature_sets.items():
        required = [feature for feature in features if feature in df.columns]
        missing_columns = [feature for feature in features if feature not in df.columns]
        required_with_label = required + (
            [label_col] if label_col in df.columns else []
        )
        usable_rows = (
            df.drop_nulls(required_with_label).height if required_with_label else 0
        )
        row_loss_columns = []
        for column in required_with_label:
            missing = df.filter(pl.col(column).is_null()).height
            if missing:
                row_loss_columns.append(f"{column}:{missing}")
        rows.append(
            {
                "feature_set": name,
                "usable_rows": usable_rows,
                "required_columns": len(features),
                "missing_columns": ", ".join(missing_columns),
                "row_loss_columns": ", ".join(row_loss_columns),
            }
        )
    return pl.DataFrame(rows).sort("usable_rows", descending=True)

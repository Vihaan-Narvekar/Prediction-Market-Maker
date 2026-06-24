import polars as pl

from eventmm.datasets.coverage import (
    compute_column_coverage,
    compute_feature_set_coverage,
)


def test_compute_column_coverage():
    df = pl.DataFrame({"a": [1, None], "b": [2, 3]})

    coverage = compute_column_coverage(df)
    rows = {row["column"]: row for row in coverage.to_dicts()}

    assert rows["a"]["coverage_pct"] == 50
    assert rows["b"]["coverage_pct"] == 100


def test_compute_feature_set_coverage():
    df = pl.DataFrame({"x": [1, None, 3], "label": [1, 0, None]})

    coverage = compute_feature_set_coverage(df, {"simple": ["x"]})

    assert coverage["usable_rows"][0] == 1

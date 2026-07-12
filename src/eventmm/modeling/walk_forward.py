from typing import Any

import polars as pl

from eventmm.modeling.baselines import (
    market_midpoint_probability,
    microprice_probability,
)
from eventmm.modeling.evaluation import evaluate_probabilities
from eventmm.modeling.models import make_logistic_regression_model
from eventmm.modeling.splits import contract_date_walk_forward


def evaluate_walk_forward(
    df: pl.DataFrame,
    *,
    feature_cols: list[str],
    label_col: str = "label",
    min_train_dates: int = 3,
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    usable = df.drop_nulls(feature_cols + [label_col, "contract_date"])
    for fold, (train, test) in enumerate(
        contract_date_walk_forward(usable, min_train_dates=min_train_dates), start=1
    ):
        if len(train) == 0 or len(test) == 0 or train[label_col].n_unique() < 2:
            continue
        test_date = str(test["contract_date"][0])
        model = make_logistic_regression_model(f"walk_forward_{fold}").fit(
            train.select(feature_cols).to_pandas(), train[label_col].to_pandas()
        )
        scorers = {
            "logistic": model.predict_proba(test.select(feature_cols).to_pandas())
        }
        if "market_mid" in test.columns:
            scorers["market_midpoint"] = market_midpoint_probability(test)
        if "market_microprice" in test.columns:
            scorers["microprice"] = microprice_probability(test)
        for name, probabilities in scorers.items():
            rows.append(
                {
                    "fold": fold,
                    "test_date": test_date,
                    "model": name,
                    "train_rows": len(train),
                    "test_rows": len(test),
                    **evaluate_probabilities(test[label_col], probabilities),
                }
            )
    return pl.DataFrame(rows)

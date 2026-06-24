import polars as pl

from eventmm.modeling.evaluation import evaluate_probabilities
from eventmm.modeling.splits import contract_date_split
from eventmm.signals.edge import add_edge_columns


def test_evaluate_probabilities():
    metrics = evaluate_probabilities([0, 1], [0.1, 0.9])

    assert metrics["log_loss"] < 0.2
    assert metrics["brier_score"] < 0.02


def test_contract_date_split_orders_dates():
    df = pl.DataFrame(
        {
            "contract_date": ["2026-06-01", "2026-06-02", "2026-06-03"],
            "value": [1, 2, 3],
        }
    )

    train, val, test = contract_date_split(df, train_frac=1 / 3, val_frac=1 / 3)

    assert train["value"].to_list() == [1]
    assert val["value"].to_list() == [2]
    assert test["value"].to_list() == [3]


def test_add_edge_columns():
    out = add_edge_columns(pl.DataFrame({"p_model": [0.6], "market_mid": [55.0]}))

    assert round(out["edge_mid"][0], 4) == 0.05

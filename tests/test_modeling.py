import polars as pl

from eventmm.modeling.evaluation import evaluate_probabilities
from eventmm.modeling.splits import contract_date_split, contract_date_walk_forward
from eventmm.modeling.walk_forward import evaluate_walk_forward
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
    out = add_edge_columns(
        pl.DataFrame(
            {
                "p_model": [0.6],
                "market_mid": [55.0],
                "best_yes_ask": [57.0],
                "best_no_ask": [45.0],
            }
        )
    )

    assert round(out["edge_mid"][0], 4) == 0.05
    assert out["yes_edge_to_ask_cents"][0] == 3
    assert out["no_edge_to_ask_cents"][0] == -5


def test_contract_date_walk_forward_is_strictly_ordered():
    df = pl.DataFrame(
        {"contract_date": ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]}
    )
    folds = contract_date_walk_forward(df, min_train_dates=2)
    assert len(folds) == 2
    assert folds[0][0]["contract_date"].to_list() == ["2026-06-01", "2026-06-02"]
    assert folds[0][1]["contract_date"].to_list() == ["2026-06-03"]


def test_walk_forward_scores_logistic_and_market_baseline():
    df = pl.DataFrame(
        {
            "contract_date": [
                date
                for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
                for _ in range(2)
            ],
            "market_mid": [20.0, 80.0] * 4,
            "market_microprice": [25.0, 75.0] * 4,
            "label": [0, 1] * 4,
        }
    )
    results = evaluate_walk_forward(df, feature_cols=["market_mid"], min_train_dates=2)
    assert results["test_date"].n_unique() == 2
    assert set(results["model"].to_list()) == {
        "logistic",
        "market_midpoint",
        "microprice",
    }

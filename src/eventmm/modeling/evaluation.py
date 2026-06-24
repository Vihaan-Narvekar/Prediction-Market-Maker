import numpy as np
import polars as pl
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def evaluate_probabilities(y_true, p_hat) -> dict[str, float | None]:
    y = np.asarray(y_true)
    p = np.asarray(p_hat).clip(0.001, 0.999)
    metrics: dict[str, float | None] = {
        "log_loss": float(log_loss(y, p)),
        "brier_score": float(brier_score_loss(y, p)),
    }
    metrics["roc_auc"] = (
        float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else None
    )
    return metrics


def calibration_table(y_true, p_hat, bins: int = 10) -> pl.DataFrame:
    df = pl.DataFrame({"label": y_true, "p_hat": p_hat})
    return (
        df.with_columns(
            (pl.col("p_hat") * bins)
            .floor()
            .clip(0, bins - 1)
            .cast(pl.Int64)
            .alias("bucket")
        )
        .group_by("bucket")
        .agg(
            pl.len().alias("n"),
            pl.col("p_hat").mean().alias("avg_p_hat"),
            pl.col("label").mean().alias("empirical_yes_rate"),
        )
        .sort("bucket")
    )

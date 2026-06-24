from dataclasses import dataclass

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class SklearnProbabilityModel:
    name: str
    pipeline: Pipeline

    def fit(self, X, y) -> "SklearnProbabilityModel":
        self.pipeline.fit(X, y)
        return self

    def predict_proba(self, X) -> np.ndarray:
        return self.pipeline.predict_proba(X)[:, 1]

    def save(self, path) -> None:
        joblib.dump(self, path)


def make_logistic_regression_model(
    name: str = "weather_logistic",
) -> SklearnProbabilityModel:
    return SklearnProbabilityModel(
        name=name,
        pipeline=Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000)),
            ]
        ),
    )

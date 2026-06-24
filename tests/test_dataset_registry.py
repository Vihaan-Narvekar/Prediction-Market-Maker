from eventmm.datasets.registry import DatasetRegistry


def test_dataset_registry_round_trip(tmp_path):
    registry = DatasetRegistry(tmp_path)
    registry.write_metadata(
        "weather_v1",
        start="2026-06-01",
        end="2026-06-30",
        market_universe="weather",
        sources={"nws": "forecast/hourly"},
        feature_tables=["book_features"],
        label_table="market_outcomes",
        row_counts={"dataset": 1},
    )

    assert registry.list_datasets() == ["weather_v1"]
    assert registry.describe("weather_v1")["row_counts"]["dataset"] == 1

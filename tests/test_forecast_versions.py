from datetime import datetime, timezone

from eventmm.external.forecast_versions import build_nws_forecast_version_row


def test_build_nws_forecast_version_row(tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("{}")

    row = build_nws_forecast_version_row(
        location="NYC",
        collection_ts=datetime(2026, 6, 23, tzinfo=timezone.utc),
        raw_response_path=raw_path,
        forecast_payload={
            "properties": {
                "generatedAt": "2026-06-23T10:00:00Z",
                "periods": [
                    {
                        "startTime": "2026-06-23T11:00:00Z",
                        "endTime": "2026-06-23T12:00:00Z",
                    }
                ],
            }
        },
    )

    assert row["location"] == "NYC"
    assert row["forecast_valid_start"] == "2026-06-23T11:00:00Z"
    assert row["hash"]

from pathlib import Path

import polars as pl

from eventmm.datasets.manifest import verify_dataset_manifest, write_dataset_manifest


def test_dataset_manifest_records_and_verifies_hashes(tmp_path: Path):
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    output = dataset_dir / "part-0.parquet"
    source = tmp_path / "source.parquet"
    pl.DataFrame({"x": [1]}).write_parquet(output)
    pl.DataFrame({"source": [2]}).write_parquet(source)

    manifest = write_dataset_manifest(
        dataset_dir,
        dataset_name="test",
        source_paths={"source": [source]},
        build_config={"mode": "test"},
    )
    assert verify_dataset_manifest(manifest) == []

    pl.DataFrame({"source": [3]}).write_parquet(source)
    assert verify_dataset_manifest(manifest) == [f"hash mismatch: {source}"]

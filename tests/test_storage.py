from eventmm.data.duckdb_client import DuckDBClient
from eventmm.data.parquet_writer import BufferedParquetWriter


def test_buffered_parquet_writer_flushes(tmp_path):
    writer = BufferedParquetWriter(tmp_path, "book_features", flush_size=2)

    writer.append({"market_ticker": "TEST", "yes_spread": 5})
    writer.append({"market_ticker": "TEST", "yes_spread": 6})

    assert not writer.buffer
    assert list((tmp_path / "book_features").glob("*.parquet"))


def test_duckdb_client_query(tmp_path):
    client = DuckDBClient(tmp_path / "eventmm.duckdb")
    try:
        result = client.query("select 1 as value")
    finally:
        client.close()

    assert result["value"].iloc[0] == 1

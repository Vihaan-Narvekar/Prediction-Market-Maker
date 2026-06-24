from pathlib import Path
from typing import Any

import duckdb


class DuckDBClient:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(db_path))

    def query(self, sql: str) -> Any:
        return self.conn.sql(sql).df()

    def close(self) -> None:
        self.conn.close()

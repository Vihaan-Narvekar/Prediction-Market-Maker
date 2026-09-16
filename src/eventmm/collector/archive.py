"""Single-writer SQLite archive. A successful append means a FULL WAL commit."""

import fcntl
import sqlite3
import time
from pathlib import Path
from typing import Any

import orjson


class ArchiveError(RuntimeError):
    """Fatal: never reconnect and silently continue after losing persistence."""


class Archive:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = path.with_suffix(path.suffix + ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.db = sqlite3.connect(path)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_ns INTEGER NOT NULL,
                    monotonic_ns INTEGER NOT NULL,
                    session TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS records_kind ON records(kind, id);
                CREATE TABLE IF NOT EXISTS checkpoints (
                    key TEXT PRIMARY KEY, value BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY, payload BLOB NOT NULL
                );
                PRAGMA user_version=1;
            """)
        except Exception:
            self.lock.close()
            raise

    def append(self, kind: str, payload: Any, session: str = "") -> int:
        raw = (
            payload
            if isinstance(payload, bytes)
            else (
                payload.encode()
                if isinstance(payload, str)
                else orjson.dumps(payload, default=str)
            )
        )
        try:
            with self.db:
                cursor = self.db.execute(
                    "INSERT INTO records(received_ns,monotonic_ns,session,kind,payload) "
                    "VALUES(?,?,?,?,?)",
                    (time.time_ns(), time.monotonic_ns(), session, kind, raw),
                )
            assert cursor.lastrowid is not None
            return cursor.lastrowid
        except sqlite3.Error as exc:
            raise ArchiveError("Archive write failed") from exc

    def checkpoint(self, key: str, value: Any) -> None:
        try:
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO checkpoints VALUES(?,?)",
                    (key, orjson.dumps(value, default=str)),
                )
        except sqlite3.Error as exc:
            raise ArchiveError("Checkpoint write failed") from exc

    def get_checkpoint(self, key: str, default: Any = None) -> Any:
        row = self.db.execute(
            "SELECT value FROM checkpoints WHERE key=?", (key,)
        ).fetchone()
        return orjson.loads(row[0]) if row else default

    def trade(self, payload: dict) -> None:
        try:
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO trades VALUES(?,?)",
                    (payload["trade_id"], orjson.dumps(payload, default=str)),
                )
        except sqlite3.Error as exc:
            raise ArchiveError("Trade write failed") from exc

    def close(self) -> None:
        self.db.close()
        self.lock.close()

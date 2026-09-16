"""Independent child restart loops, graceful signals, and freshness supervision."""

import asyncio
import sqlite3
import time
from pathlib import Path

import orjson
import structlog

logger = structlog.get_logger()


def health(path: Path, max_age: float) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM checkpoints WHERE key='health'").fetchone()
    if not row:
        raise RuntimeError("No completed heartbeat")
    status = orjson.loads(row[0])
    now = time.time()
    if now - status["heartbeat"] > max_age:
        raise RuntimeError("Stale worker heartbeat")
    if "connected" in status:
        if (
            status.get("last_discovery") is None
            or now - status["last_discovery"] > max_age
        ):
            raise RuntimeError("Market discovery is stale")
        last_reconcile = status.get("last_reconcile") or status.get("started_at", now)
        if now - last_reconcile > status.get("reconcile_max_age", 1800):
            raise RuntimeError("Trade/book reconciliation is stale")
        if status["markets"] and (
            not status["connected"]
            or status.get("last_frame") is None
            or now - status["last_frame"] > max_age
        ):
            raise RuntimeError("Market stream is disconnected or stale")
    return status


async def terminate(process):
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 20)
        except TimeoutError:
            process.kill()
            await process.wait()


async def supervise_worker(
    name: str, command: list[str], archive_path: Path, max_age: float
):
    delay = 2.0
    while True:
        process = await asyncio.create_subprocess_exec(*command)
        started = time.monotonic()
        logger.info("worker_started", worker=name, pid=process.pid)
        try:
            while True:
                try:
                    code = await asyncio.wait_for(process.wait(), 15)
                    logger.warning("worker_exited", worker=name, code=code)
                    break
                except TimeoutError:
                    if time.monotonic() - started < max_age:
                        continue
                    try:
                        health(archive_path, max_age)
                    except (RuntimeError, sqlite3.Error, OSError) as exc:
                        logger.warning("worker_unhealthy", worker=name, error=str(exc))
                        break
        finally:
            await terminate(process)
        if time.monotonic() - started > max_age * 2:
            delay = 2.0
        await asyncio.sleep(delay)
        delay = min(60, delay * 2)


async def supervise(workers):
    async with asyncio.TaskGroup() as group:
        for worker in workers:
            group.create_task(supervise_worker(*worker))

"""DuckDB over the Parquet archive.

In-process, no cluster, no cost. Ten million rows of columnar Parquet is far
below where DuckDB struggles - which is exactly the argument for it over Spark
or Athena at this size, and the README carries the measured numbers.

The same queries run against a local directory or an S3 bucket (MinIO locally,
S3 in AWS); only the root URI changes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb

from ..config import settings

log = logging.getLogger("onside.archive")

_lock = threading.Lock()
_db: duckdb.DuckDBPyConnection | None = None


class ArchiveUnavailable(RuntimeError):
    """The Parquet archive could not be opened from anywhere."""


def _glob(root: str | None = None) -> str:
    root = (root or settings().archive_uri).rstrip("/")
    return f"{root}/competition_id=*/season_id=*/*.parquet"


def _local_root() -> Path:
    return settings().data_dir / "archive" / "events"


def _view(con: duckdb.DuckDBPyConnection, root: str | None = None) -> None:
    # Every file shares one schema (archive/writer.py), so no union_by_name:
    # that would make DuckDB open all 3,961 files just to plan a query.
    con.execute(
        f"CREATE OR REPLACE VIEW events AS SELECT * FROM read_parquet('{_glob(root)}', "
        "hive_partitioning = true)"
    )
    # The view is lazy; touch it now so a bad store fails here, where there is
    # a fallback, and not in the middle of someone's request.
    con.execute("SELECT 1 FROM events LIMIT 1").fetchall()


def connect() -> duckdb.DuckDBPyConnection:
    """One database per process; each query gets its own cursor.

    DuckDB connections are not thread-safe, but cursors from one connection
    are, and they share its catalog - so the `events` view (whose creation
    reads the archive's file list) is built once, not once per API thread.
    """
    global _db
    with _lock:
        if _db is not None:
            return _db
        con = duckdb.connect(database=":memory:")
        con.execute("SET threads TO 8")
        s = settings()
        if s.archive_is_s3:
            import os

            con.execute("INSTALL httpfs; LOAD httpfs;")
            ep = urlparse(s.s3_endpoint)
            key = os.environ.get("AWS_ACCESS_KEY_ID")
            # A DuckDB secret, not the legacy SET s3_* settings, which current
            # DuckDB no longer applies to every request. Explicit keys locally
            # (MinIO); the task role's credential chain in AWS.
            auth = (
                f"KEY_ID '{key}', SECRET '{os.environ.get('AWS_SECRET_ACCESS_KEY', '')}'"
                if key
                else "PROVIDER credential_chain"
            )
            con.execute(
                f"CREATE OR REPLACE SECRET archive (TYPE s3, {auth}, REGION '{s.region}', "
                f"ENDPOINT '{ep.netloc}', URL_STYLE '{'path' if s.is_local else 'vhost'}', "
                f"USE_SSL {'true' if ep.scheme == 'https' else 'false'})"
            )
        try:
            _view(con)
        except Exception as exc:  # noqa: BLE001 - any failure to open it
            # The object store is the source of truth in AWS; locally the same
            # files usually sit on disk too. Serve from there rather than fail,
            # and say so in the log - nothing is silently different.
            local = _local_root()
            if s.archive_is_s3 and any(local.glob("competition_id=*/season_id=*/*.parquet")):
                log.warning("archive at %s unavailable (%s); reading %s", s.archive_uri, exc, local)
                _view(con, str(local))
            else:
                con.close()
                raise ArchiveUnavailable(str(exc)) from exc
        _db = con
        return con


def query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cur = connect().cursor()
    try:
        cur.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        cur.close()


def reset() -> None:
    """Drop the connection, e.g. after the archive is rebuilt."""
    global _db
    with _lock:
        if _db is not None:
            _db.close()
            _db = None

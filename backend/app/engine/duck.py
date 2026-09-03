"""DuckDB connection factory.

One connection per reconciliation run. DuckDB is embedded, so this is a process-
local analytical engine — no server, no network hop, and it reads Parquet with
predicate pushdown, which is the whole reason we normalize to Parquet first.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import duckdb

from app.config import settings


@contextlib.contextmanager
def duck_connection(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(database=":memory:", read_only=read_only)
    try:
        con.execute(f"SET threads TO {settings.duckdb_threads}")
        con.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
        con.execute("SET preserve_insertion_order = false")
        yield con
    finally:
        con.close()


def register_parquet(con: duckdb.DuckDBPyConnection, view: str, path: str) -> None:
    """Expose a Parquet file as a view. Nothing is read until a query touches it."""
    con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM read_parquet(?)", [path])


def table_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

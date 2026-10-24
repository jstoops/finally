"""SQLite connection helpers, schema initialization and transactions."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_USER = "default"
DEFAULT_CASH = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    """Current UTC time as ISO 8601 with a Z suffix, seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection: dict-friendly rows, foreign keys on, WAL, parent dir created.

    The connection is in autocommit mode (``isolation_level=None``): a statement run
    outside :func:`transaction` commits immediately. Group related writes in
    ``with transaction(conn):`` to make them atomic.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back if the block raises."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def seed_watchlist(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> None:
    """Insert the default watchlist (INSERT OR IGNORE). Rowid keeps the seeded order."""
    added_at = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [(new_id(), user_id, ticker, added_at) for ticker in DEFAULT_WATCHLIST],
    )


def init_db(db_path: str) -> None:
    """Create the schema and seed default data. Idempotent.

    The default watchlist is seeded only when the user profile is first created, so a
    default ticker the user removed is not re-added on the next restart.
    """
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        with transaction(conn):
            cur = conn.execute(
                "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                (DEFAULT_USER, DEFAULT_CASH, now_iso()),
            )
            if cur.rowcount == 1:
                seed_watchlist(conn, DEFAULT_USER)
    finally:
        conn.close()

"""SQLite persistence layer for FinAlly (stdlib sqlite3, no ORM).

Connections are autocommit; group writes with ``with transaction(conn):``.
Rows are returned as plain dicts; timestamps are ISO 8601 UTC with a Z suffix.
"""

from .connection import (
    DEFAULT_CASH,
    DEFAULT_USER,
    DEFAULT_WATCHLIST,
    connect,
    init_db,
    now_iso,
    transaction,
)
from .repository import (
    add_watchlist,
    delete_position,
    get_cash,
    get_position,
    get_watchlist_entry,
    insert_chat_message,
    insert_snapshot,
    insert_trade,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_watchlist,
    remove_watchlist,
    reset_user,
    set_cash,
    upsert_position,
)

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_USER",
    "DEFAULT_WATCHLIST",
    "connect",
    "init_db",
    "now_iso",
    "transaction",
    "get_cash",
    "set_cash",
    "list_watchlist",
    "get_watchlist_entry",
    "add_watchlist",
    "remove_watchlist",
    "list_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "insert_trade",
    "insert_snapshot",
    "list_snapshots",
    "insert_chat_message",
    "list_chat_messages",
    "reset_user",
]

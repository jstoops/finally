"""Repository functions for each table. None of them commit; callers own transactions."""

from __future__ import annotations

import json
import sqlite3

from .connection import DEFAULT_CASH, DEFAULT_USER, new_id, now_iso, seed_watchlist


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


# --- users_profile ---------------------------------------------------------


def get_cash(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> float:
    row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise LookupError(f"No user profile for {user_id!r}")
    return float(row["cash_balance"])


def set_cash(conn: sqlite3.Connection, cash: float, user_id: str = DEFAULT_USER) -> None:
    conn.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET cash_balance = excluded.cash_balance",
        (user_id, float(cash), now_iso()),
    )


# --- watchlist -------------------------------------------------------------


def list_watchlist(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[dict]:
    rows = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_watchlist_entry(
    conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER
) -> dict | None:
    row = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, _norm(ticker)),
    ).fetchone()
    return dict(row) if row else None


def add_watchlist(
    conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER
) -> tuple[dict, bool]:
    """Add a ticker; returns ``(entry, created)``. Existing entries are returned unchanged."""
    ticker = _norm(ticker)
    cur = conn.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (new_id(), user_id, ticker, now_iso()),
    )
    entry = get_watchlist_entry(conn, ticker, user_id)
    assert entry is not None
    return entry, cur.rowcount == 1


def remove_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER) -> bool:
    cur = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker))
    )
    return cur.rowcount > 0


# --- positions -------------------------------------------------------------


def list_positions(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[dict]:
    rows = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
        "WHERE user_id = ? ORDER BY ticker",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_position(conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER) -> dict | None:
    row = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
        "WHERE user_id = ? AND ticker = ?",
        (user_id, _norm(ticker)),
    ).fetchone()
    return dict(row) if row else None


def upsert_position(
    conn: sqlite3.Connection,
    ticker: str,
    quantity: float,
    avg_cost: float,
    user_id: str = DEFAULT_USER,
) -> None:
    conn.execute(
        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, ticker) DO UPDATE SET "
        "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
        "updated_at = excluded.updated_at",
        (new_id(), user_id, _norm(ticker), float(quantity), float(avg_cost), now_iso()),
    )


def delete_position(conn: sqlite3.Connection, ticker: str, user_id: str = DEFAULT_USER) -> None:
    conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker)))


# --- trades ----------------------------------------------------------------


def insert_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = DEFAULT_USER,
) -> dict:
    trade = {
        "id": new_id(),
        "ticker": _norm(ticker),
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            trade["id"],
            user_id,
            trade["ticker"],
            side,
            trade["quantity"],
            trade["price"],
            trade["executed_at"],
        ),
    )
    return trade


# --- portfolio_snapshots ---------------------------------------------------


def insert_snapshot(
    conn: sqlite3.Connection, total_value: float, user_id: str = DEFAULT_USER
) -> dict:
    snapshot = {"total_value": float(total_value), "recorded_at": now_iso()}
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (new_id(), user_id, snapshot["total_value"], snapshot["recorded_at"]),
    )
    return snapshot


def list_snapshots(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> list[dict]:
    rows = conn.execute(
        "SELECT total_value, recorded_at FROM portfolio_snapshots "
        "WHERE user_id = ? ORDER BY recorded_at, rowid",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- chat_messages ---------------------------------------------------------


def _chat_row(row: sqlite3.Row) -> dict:
    msg = dict(row)
    msg["actions"] = json.loads(msg["actions"]) if msg["actions"] is not None else None
    return msg


def insert_chat_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | None = None,
    user_id: str = DEFAULT_USER,
) -> dict:
    msg = {
        "id": new_id(),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            msg["id"],
            user_id,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            msg["created_at"],
        ),
    )
    return msg


def list_chat_messages(
    conn: sqlite3.Connection, limit: int = 50, user_id: str = DEFAULT_USER
) -> list[dict]:
    """The last ``limit`` messages, oldest first."""
    rows = conn.execute(
        "SELECT id, role, content, actions, created_at FROM chat_messages "
        "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, max(int(limit), 0)),
    ).fetchall()
    return [_chat_row(r) for r in reversed(rows)]


# --- reset -----------------------------------------------------------------


def reset_user(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> None:
    """Restore the seeded state: default cash and watchlist; no positions, trades,
    snapshots or chat. Does not commit; wrap in ``transaction``."""
    set_cash(conn, DEFAULT_CASH, user_id)
    for table in ("positions", "trades", "portfolio_snapshots", "chat_messages", "watchlist"):
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    seed_watchlist(conn, user_id)

"""Portfolio valuation, watchlist pricing and snapshots (PLAN §8)."""

from __future__ import annotations

import sqlite3

from app import db
from app.market import PriceCache


def build_portfolio(conn: sqlite3.Connection, price_cache: PriceCache) -> dict:
    """Return the GET /api/portfolio body.

    A held ticker with no cached price is valued at its average cost.
    """
    cash = db.get_cash(conn)
    rows = []
    for pos in db.list_positions(conn):
        quantity = pos["quantity"]
        avg_cost = pos["avg_cost"]
        cached = price_cache.get_price(pos["ticker"])
        price = cached if cached is not None else avg_cost
        rows.append((pos, quantity, avg_cost, price, quantity * price))

    positions_value = sum(row[4] for row in rows)
    positions = []
    for pos, quantity, avg_cost, price, market_value in rows:
        pnl = (price - avg_cost) * quantity
        pnl_percent = (price - avg_cost) / avg_cost * 100 if avg_cost else 0.0
        positions.append(
            {
                "ticker": pos["ticker"],
                "quantity": quantity,
                "avg_cost": avg_cost,
                "current_price": round(price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_percent": round(pnl_percent, 4),
                "weight": round(market_value / positions_value, 4) if positions_value else 0.0,
            }
        )

    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(cash + positions_value, 2),
        "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
        "positions": positions,
    }


def watchlist_item(entry: dict, price_cache: PriceCache) -> dict:
    """One GET /api/watchlist entry; prices are None until the first price arrives."""
    update = price_cache.get(entry["ticker"])
    return {
        "ticker": entry["ticker"],
        "price": update.price if update else None,
        "open_price": update.open_price if update else None,
        "added_at": entry["added_at"],
    }


def build_watchlist(conn: sqlite3.Connection, price_cache: PriceCache) -> list[dict]:
    """All watchlist entries with live prices, in `added_at` order."""
    return [watchlist_item(entry, price_cache) for entry in db.list_watchlist(conn)]


def record_snapshot(conn: sqlite3.Connection, price_cache: PriceCache) -> dict:
    """Insert a snapshot of the current total portfolio value and commit."""
    total = build_portfolio(conn, price_cache)["total_value"]
    snapshot = db.insert_snapshot(conn, total)
    conn.commit()
    return snapshot

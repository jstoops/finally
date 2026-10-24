"""Trades, watchlist changes and reset, keeping tracked tickers in sync (PLAN §6, §7).

Tracked tickers (the ones the market source prices) are watchlist ∪ held positions.
Each public coroutine opens its own connection; DB work runs synchronously on the
event loop (queries are tiny) so no two coroutines interleave inside a transaction.
"""

from __future__ import annotations

import logging
import math
import sqlite3

from app import db
from app.market import PriceCache
from app.state import AppState

from .errors import TradeError
from .tickers import normalize_ticker
from .valuation import record_snapshot

logger = logging.getLogger(__name__)

QUANTITY_DECIMALS = 4
DUST = 1e-6


def _fmt_qty(quantity: float) -> str:
    return f"{quantity:.4f}".rstrip("0").rstrip(".")


def _validate_quantity(quantity: float) -> float:
    try:
        value = float(quantity)
    except (TypeError, ValueError):
        raise TradeError("Quantity must be a number") from None
    if not math.isfinite(value):
        raise TradeError("Quantity must be a number")
    value = round(value, QUANTITY_DECIMALS)
    if value <= 0:
        raise TradeError("Quantity must be greater than 0")
    return value


def apply_trade(
    conn: sqlite3.Connection,
    price_cache: PriceCache,
    ticker: str,
    side: str,
    quantity: float,
) -> dict:
    """Validate and execute a market order in one transaction (no snapshot).

    Returns the trade dict. Raises TradeError on any rule violation, leaving the
    database unchanged.
    """
    ticker = normalize_ticker(ticker)
    side = str(side).strip().lower()
    if side not in ("buy", "sell"):
        raise TradeError("Side must be 'buy' or 'sell'")
    quantity = _validate_quantity(quantity)

    price = price_cache.get_price(ticker)
    if price is None:
        raise TradeError(f"No price available for {ticker}. Add it to your watchlist first.")

    with db.transaction(conn):
        cash = db.get_cash(conn)
        position = db.get_position(conn, ticker)
        held = position["quantity"] if position else 0.0
        avg_cost = position["avg_cost"] if position else 0.0

        if side == "buy":
            cost = quantity * price
            if cost > cash:
                raise TradeError(f"Insufficient cash (need ${cost:,.2f}, have ${cash:,.2f})")
            new_qty = held + quantity
            new_avg = (held * avg_cost + quantity * price) / new_qty
            db.set_cash(conn, cash - cost)
            db.upsert_position(conn, ticker, new_qty, new_avg)
        else:
            if quantity > held + DUST:
                raise TradeError(
                    f"Insufficient shares of {ticker} "
                    f"(have {_fmt_qty(held)}, trying to sell {_fmt_qty(quantity)})"
                )
            remaining = held - quantity
            db.set_cash(conn, cash + quantity * price)
            if remaining < DUST:
                db.delete_position(conn, ticker)
            else:
                db.upsert_position(conn, ticker, remaining, avg_cost)

        return db.insert_trade(conn, ticker, side, quantity, price)


async def execute_trade(state: AppState, ticker: str, side: str, quantity: float) -> dict:
    """Execute a market order, record a snapshot, and stop pricing an unwatched
    ticker that was sold to zero. Returns the trade dict; raises TradeError."""
    conn = state.connect()
    try:
        trade = apply_trade(conn, state.price_cache, ticker, side, quantity)
        record_snapshot(conn, state.price_cache)
        symbol = trade["ticker"]
        drop = (
            trade["side"] == "sell"
            and db.get_position(conn, symbol) is None
            and db.get_watchlist_entry(conn, symbol) is None
        )
    finally:
        conn.close()
    if drop:
        await state.market_source.remove_ticker(symbol)
    return trade


async def add_to_watchlist(state: AppState, ticker: str) -> tuple[dict, bool]:
    """Add a ticker (idempotent) and start pricing it. Returns (entry, created)."""
    symbol = normalize_ticker(ticker)
    conn = state.connect()
    try:
        entry, created = db.add_watchlist(conn, symbol)
        conn.commit()
    finally:
        conn.close()
    await state.market_source.add_ticker(symbol)
    return entry, created


async def remove_from_watchlist(state: AppState, ticker: str) -> bool:
    """Remove a ticker; keep pricing it if a position is held. False if not listed."""
    symbol = normalize_ticker(ticker)
    conn = state.connect()
    try:
        removed = db.remove_watchlist(conn, symbol)
        conn.commit()
        held = db.get_position(conn, symbol) is not None
    finally:
        conn.close()
    if removed and not held:
        await state.market_source.remove_ticker(symbol)
    return removed


async def sync_tracked_tickers(state: AppState) -> None:
    """Make the market source track exactly watchlist ∪ held positions."""
    conn = state.connect()
    try:
        wanted = {e["ticker"] for e in db.list_watchlist(conn)}
        wanted |= {p["ticker"] for p in db.list_positions(conn)}
    finally:
        conn.close()
    current = set(state.market_source.get_tickers())
    for symbol in sorted(current - wanted):
        await state.market_source.remove_ticker(symbol)
    for symbol in sorted(wanted - current):
        await state.market_source.add_ticker(symbol)


async def reset_account(state: AppState) -> None:
    """Restore the seeded account, re-sync tracked tickers, record a snapshot."""
    conn = state.connect()
    try:
        with db.transaction(conn):
            db.reset_user(conn)
    finally:
        conn.close()
    await sync_tracked_tickers(state)
    conn = state.connect()
    try:
        record_snapshot(conn, state.price_cache)
    finally:
        conn.close()

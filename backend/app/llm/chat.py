"""Chat orchestration: PLAN §9 steps 1-10."""

from __future__ import annotations

import logging
from contextlib import closing
from typing import TYPE_CHECKING

from app import db, portfolio

from .client import LLMNotConfigured, call_llm, is_configured, is_mock_mode
from .mock import mock_response
from .prompt import build_context, build_messages
from .schema import ChatResponse, TradeRequest, WatchlistChange

if TYPE_CHECKING:
    from app.state import AppState

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20  # prior messages sent to the LLM
UNEXPECTED_ERROR = "unexpected error"


def _qty(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _error_text(exc: Exception) -> str:
    """User-facing error text from a portfolio error; hide internals of anything else."""
    if isinstance(exc, portfolio.PortfolioError):
        return str(exc) or UNEXPECTED_ERROR
    logger.exception("Unexpected error executing chat action")
    return UNEXPECTED_ERROR


def _lower_first(text: str) -> str:
    """'Insufficient cash ...' -> 'insufficient cash ...', but keep 'TSLA ...' intact."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _display_ticker(raw: str) -> str:
    try:
        return portfolio.normalize_ticker(raw)
    except portfolio.PortfolioError:
        return raw.strip().upper()


async def _apply_watchlist_change(state: AppState, change: WatchlistChange) -> dict:
    result = {"ticker": _display_ticker(change.ticker), "action": change.action}
    try:
        if change.action == "add":
            entry, _created = await portfolio.add_to_watchlist(state, change.ticker)
            result["ticker"] = entry["ticker"]
        elif not await portfolio.remove_from_watchlist(state, change.ticker):
            raise portfolio.PortfolioError(f"{result['ticker']} is not on your watchlist")
    except Exception as exc:
        return {**result, "status": "failed", "error": _error_text(exc)}
    return {**result, "status": "executed"}


async def _apply_trade(state: AppState, trade: TradeRequest) -> dict:
    result = {
        "ticker": _display_ticker(trade.ticker),
        "side": trade.side,
        "quantity": trade.quantity,
    }
    try:
        executed = await portfolio.execute_trade(state, trade.ticker, trade.side, trade.quantity)
    except Exception as exc:
        return {**result, "status": "failed", "error": _error_text(exc)}
    return {
        **result,
        "ticker": executed["ticker"],
        "quantity": executed["quantity"],
        "status": "executed",
        "price": executed["price"],
    }


def _failure_note(action: dict) -> str:
    error = _lower_first(action["error"])
    if "side" in action:
        what = f"{action['side']} {_qty(action['quantity'])} {action['ticker']}"
    elif action["action"] == "add":
        what = f"add {action['ticker']} to your watchlist"
    else:
        what = f"remove {action['ticker']} from your watchlist"
    return f"⚠️ Couldn't {what}: {error}"


async def execute_actions(state: AppState, response: ChatResponse) -> dict | None:
    """Watchlist changes first, then trades; each independent. None if none requested."""
    if not response.trades and not response.watchlist_changes:
        return None
    watchlist_results = [
        await _apply_watchlist_change(state, c) for c in response.watchlist_changes
    ]
    trade_results = [await _apply_trade(state, t) for t in response.trades]
    return {"trades": trade_results, "watchlist_changes": watchlist_results}


def compose_message(text: str, actions: dict | None) -> str:
    """Append a templated note for each failed action (no second LLM call)."""
    if not actions:
        return text
    failed = [
        a for a in actions["watchlist_changes"] + actions["trades"] if a["status"] == "failed"
    ]
    if not failed:
        return text
    notes = "\n".join(_failure_note(a) for a in failed)
    return f"{text}\n\n{notes}" if text else notes


async def handle_chat(state: AppState, message: str) -> dict:
    """Run one chat turn and return the stored assistant message (PLAN §8 shape).

    Raises LLMNotConfigured (-> 503) before storing anything, and LLMCallFailed (-> 502)
    after the user message has been stored.
    """
    mock = is_mock_mode()
    if not mock and not is_configured():
        raise LLMNotConfigured()

    with closing(state.connect()) as conn:
        history = db.list_chat_messages(conn, limit=HISTORY_LIMIT)
        db.insert_chat_message(conn, "user", message)
        context = build_context(
            portfolio.build_portfolio(conn, state.price_cache),
            portfolio.build_watchlist(conn, state.price_cache),
        )

    if mock:
        response = mock_response(message)
    else:
        response = await call_llm(build_messages(context, history, message))

    actions = await execute_actions(state, response)
    content = compose_message(response.message, actions)

    with closing(state.connect()) as conn:
        return db.insert_chat_message(conn, "assistant", content, actions)

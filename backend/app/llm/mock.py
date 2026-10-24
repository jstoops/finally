"""Deterministic mock LLM responses for LLM_MOCK=true (PLAN §9)."""

from __future__ import annotations

import re

from .schema import ChatResponse, TradeRequest, WatchlistChange

GREETING = "Hello! I'm FinAlly, your AI trading assistant. How can I help?"

_ADD_RE = re.compile(r"\badd\s+([A-Za-z0-9.]+)", re.IGNORECASE)
_REMOVE_RE = re.compile(r"\bremove\s+([A-Za-z0-9.]+)", re.IGNORECASE)


def _ticker(match: re.Match[str]) -> str:
    # "add PYPL." -> "PYPL": a trailing sentence period isn't part of the symbol
    return match.group(1).rstrip(".").upper()


def mock_response(message: str) -> ChatResponse:
    """Match the user message case-insensitively; the first rule wins."""
    text = message.lower()
    if "buy" in text:
        return ChatResponse(
            message="Buying 1 share of AAPL.",
            trades=[TradeRequest(ticker="AAPL", side="buy", quantity=1)],
        )
    if "sell" in text:
        return ChatResponse(
            message="Selling 1 share of AAPL.",
            trades=[TradeRequest(ticker="AAPL", side="sell", quantity=1)],
        )
    if (match := _ADD_RE.search(message)) and (ticker := _ticker(match)):
        return ChatResponse(
            message=f"Adding {ticker} to your watchlist.",
            watchlist_changes=[WatchlistChange(ticker=ticker, action="add")],
        )
    if (match := _REMOVE_RE.search(message)) and (ticker := _ticker(match)):
        return ChatResponse(
            message=f"Removing {ticker} from your watchlist.",
            watchlist_changes=[WatchlistChange(ticker=ticker, action="remove")],
        )
    return ChatResponse(message=GREETING)

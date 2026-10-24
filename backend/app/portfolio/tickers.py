"""Ticker normalization (PLAN §7)."""

from __future__ import annotations

import re

from .errors import TradeError

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def normalize_ticker(raw: str) -> str:
    """Strip and uppercase `raw`; raise TradeError unless it is a well-formed symbol."""
    ticker = str(raw).strip().upper()
    if not TICKER_RE.match(ticker):
        raise TradeError(f"Invalid ticker symbol: '{str(raw).strip()}'")
    return ticker

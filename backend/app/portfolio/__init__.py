"""Portfolio subsystem: trade rules, valuation, tracked tickers, snapshots (PLAN §6-§8).

Public API (see planning/TEAM_CONTRACTS.md):
    PortfolioError, TradeError  - user-facing errors (message is the 400 body text)
    normalize_ticker            - strip + upper + validate
    build_portfolio             - GET /api/portfolio shape
    build_watchlist             - GET /api/watchlist entries with live prices
    watchlist_item              - one watchlist entry with live prices
    record_snapshot             - insert a portfolio value snapshot
    execute_trade               - market order, one transaction, then snapshot
    add_to_watchlist / remove_from_watchlist / reset_account
"""

from .errors import PortfolioError, TradeError
from .service import (
    add_to_watchlist,
    execute_trade,
    remove_from_watchlist,
    reset_account,
    sync_tracked_tickers,
)
from .tickers import normalize_ticker
from .valuation import build_portfolio, build_watchlist, record_snapshot, watchlist_item

__all__ = [
    "PortfolioError",
    "TradeError",
    "normalize_ticker",
    "build_portfolio",
    "build_watchlist",
    "watchlist_item",
    "record_snapshot",
    "execute_trade",
    "add_to_watchlist",
    "remove_from_watchlist",
    "reset_account",
    "sync_tracked_tickers",
]

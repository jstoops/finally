"""Shared runtime state, stored on `app.state.ctx` (see planning/TEAM_CONTRACTS.md)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app import db
from app.market import MarketDataSource, PriceCache


@dataclass
class AppState:
    db_path: str
    price_cache: PriceCache
    market_source: MarketDataSource

    def connect(self) -> sqlite3.Connection:
        """Open a new connection to the app database (caller closes it)."""
        return db.connect(self.db_path)

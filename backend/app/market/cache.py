"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from .models import PriceUpdate

HISTORY_SIZE = 600  # 5 minutes at 500ms


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._open_prices: dict[str, float] = {}  # First price seen per ticker
        self._history: dict[str, deque[tuple[float, float]]] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Automatically computes direction and change from the previous price.
        If this is the first update for the ticker, previous_price == price (direction='flat').
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            rounded = round(price, 2)
            open_price = self._open_prices.setdefault(ticker, rounded)

            update = PriceUpdate(
                ticker=ticker,
                price=rounded,
                previous_price=round(previous_price, 2),
                timestamp=ts,
                open_price=open_price,
            )
            self._prices[ticker] = update
            self._history.setdefault(ticker, deque(maxlen=HISTORY_SIZE)).append((ts, rounded))
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def get_history(self, ticker: str) -> list[tuple[float, float]]:
        """Last ~5 minutes of (timestamp, price) points, oldest first. Empty if untracked."""
        with self._lock:
            return list(self._history.get(ticker, ()))

    def remove(self, ticker: str) -> None:
        """Remove a ticker (price, session open and history) from the cache."""
        with self._lock:
            self._prices.pop(ticker, None)
            self._open_prices.pop(ticker, None)
            self._history.pop(ticker, None)

    @property
    def version(self) -> int:
        """Current version counter. Useful for SSE change detection."""
        return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices

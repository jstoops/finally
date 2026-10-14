"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import Lock

from .models import PricePoint, PriceUpdate


class PriceCache:
    """Latest price, session open price and recent history for each tracked ticker.

    Writers: the active MarketDataSource (simulator or Massive), via update()/remove().
    Readers: SSE stream, history endpoint, portfolio valuation, trade execution, LLM context.

    Keys are stored as given; callers pass normalized (uppercase, trimmed) tickers.
    """

    HISTORY_SECONDS: float = 300.0  # PLAN §6: last 5 minutes
    HISTORY_MAX_POINTS: int = 600  # 5 min at 500 ms; hard cap on memory per ticker

    def __init__(
        self,
        history_seconds: float = HISTORY_SECONDS,
        history_max_points: int = HISTORY_MAX_POINTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._history_seconds = history_seconds
        self._history_max_points = history_max_points
        self._clock = clock  # injectable for tests
        self._prices: dict[str, PriceUpdate] = {}
        self._history: dict[str, deque[PricePoint]] = {}
        self._lock = Lock()
        self._version = 0  # bumped on every update() and every effective remove()

    # --- Writes ---

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a price for `ticker` and return the new PriceUpdate.

        Sets open_price on the first update for the ticker and carries it forward
        afterwards. Timestamps default to receipt time and are forced to be strictly
        increasing per ticker, because the frontend chart rejects repeated times.
        """
        price = round(float(price), 2)
        with self._lock:
            ts = timestamp if timestamp is not None else self._clock()
            prev = self._prices.get(ticker)
            if prev is not None and ts <= prev.timestamp:
                ts = prev.timestamp + 0.001  # clock repeated or stepped back

            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                open_price=prev.open_price if prev else price,
                timestamp=ts,
            )
            self._prices[ticker] = update

            history = self._history.get(ticker)
            if history is None:
                history = self._history[ticker] = deque(maxlen=self._history_max_points)
            history.append(PricePoint(timestamp=ts, price=price))

            self._version += 1
            return update

    def remove(self, ticker: str) -> None:
        """Forget `ticker` entirely: latest price, session open and history."""
        with self._lock:
            existed = self._prices.pop(ticker, None) is not None
            self._history.pop(ticker, None)
            if existed:
                self._version += 1  # SSE pushes a frame without the ticker

    # --- Reads ---

    def get(self, ticker: str) -> PriceUpdate | None:
        """Latest price for a ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        """Shallow copy of all latest prices (values are immutable)."""
        with self._lock:
            return dict(self._prices)

    def get_history(self, ticker: str) -> list[PricePoint]:
        """Points from the last HISTORY_SECONDS, oldest first. [] if unknown."""
        cutoff = self._clock() - self._history_seconds
        with self._lock:
            history = self._history.get(ticker)
            if not history:
                return []
            return [p for p in history if p.timestamp >= cutoff]

    @property
    def version(self) -> int:
        """Monotonic change counter for SSE change detection."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices

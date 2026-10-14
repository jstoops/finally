"""Data models for market data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of one ticker's latest price.

    Created by PriceCache.update(), which fills previous_price and open_price.
    """

    ticker: str
    price: float  # rounded to 2 dp
    previous_price: float  # price at the previous update (== price on the first one)
    open_price: float  # session open: first price seen for this ticker this process
    timestamp: float  # Unix seconds (float), when the cache received the price

    @property
    def change(self) -> float:
        """Tick-to-tick absolute change. Used for flash direction only."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Tick-to-tick % change. NOT the UI's Chg % (see session_change_percent)."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def session_change_percent(self) -> float:
        """% change since session open: the UI's "Chg %" (PLAN §6).

        Not in the SSE payload (the frontend computes it from price and open_price);
        provided for server-side consumers such as the LLM portfolio context.
        """
        if self.open_price == 0:
            return 0.0
        return round((self.price - self.open_price) / self.open_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down' or 'flat' relative to the previous update."""
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Exactly the SSE payload fields of PLAN §6, in that order."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One point in a ticker's 5-minute history buffer."""

    timestamp: float  # Unix seconds, same clock as PriceUpdate.timestamp
    price: float

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "price": self.price}

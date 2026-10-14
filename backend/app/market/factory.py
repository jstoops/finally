"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import math
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 15.0  # suits the free tier's 5 calls/min
MIN_POLL_INTERVAL = 1.0


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource, polling every
      MASSIVE_POLL_INTERVAL seconds (default 15, minimum 1)
    - Otherwise → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        interval = _poll_interval()
        logger.info("Market data source: Massive API (poll every %.1fs)", interval)
        return MassiveDataSource(
            api_key=api_key,
            price_cache=price_cache,
            poll_interval=interval,
        )
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)


def _poll_interval() -> float:
    """Read MASSIVE_POLL_INTERVAL (seconds).

    Blank → default. Invalid, NaN or infinite → default with a warning.
    Below the minimum (including zero and negatives) → clamped to the minimum.
    """
    raw = os.environ.get("MASSIVE_POLL_INTERVAL", "").strip()
    if not raw:
        return DEFAULT_POLL_INTERVAL
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        logger.warning("Invalid MASSIVE_POLL_INTERVAL %r; using %ss", raw, DEFAULT_POLL_INTERVAL)
        return DEFAULT_POLL_INTERVAL
    if value < MIN_POLL_INTERVAL:
        logger.warning(
            "MASSIVE_POLL_INTERVAL %r is below the minimum; using %ss", raw, MIN_POLL_INTERVAL
        )
        return MIN_POLL_INTERVAL
    return value

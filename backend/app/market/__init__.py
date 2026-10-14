"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    PricePoint          - One (timestamp, price) point of history
    PriceCache          - Thread-safe store: latest, session open, history, version
    MarketDataSource    - Abstract interface for data providers
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router - FastAPI router factory: SSE stream + price history
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PricePoint, PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PricePoint",
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]

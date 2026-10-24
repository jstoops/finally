"""Fixtures for LLM tests: temp DB, seeded price cache, fake market source, env control."""

import pytest

from app import db
from app.market import MarketDataSource, PriceCache
from app.state import AppState

SEED_PRICES = {"AAPL": 190.0, "GOOGL": 175.0, "NVDA": 800.0, "TSLA": 250.0}


class FakeMarketSource(MarketDataSource):
    """Prices a newly added ticker immediately, like the simulator."""

    def __init__(self, cache: PriceCache) -> None:
        self._cache = cache
        self._tickers: set[str] = set()

    async def start(self, tickers: list[str]) -> None:
        for t in tickers:
            await self.add_ticker(t)

    async def stop(self) -> None:
        pass

    async def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker)
        if self._cache.get(ticker) is None:
            self._cache.update(ticker, SEED_PRICES.get(ticker, 100.0))

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)


@pytest.fixture
async def state(tmp_path) -> AppState:
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    cache = PriceCache()
    source = FakeMarketSource(cache)
    await source.start(list(db.DEFAULT_WATCHLIST))
    return AppState(db_path=db_path, price_cache=cache, market_source=source)


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture
def real_mode(monkeypatch):
    """Not mock mode, with a dummy key; tests must stub call_llm / litellm.acompletion."""
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

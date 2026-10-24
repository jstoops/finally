"""Pytest configuration and fixtures."""

from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import db
from app.market import MarketDataSource, PriceCache
from app.state import AppState


class FakeSource(MarketDataSource):
    """Deterministic market source: prices a ticker once, at a fixed price, when added.

    Prices come from `prices` (default 100.0); `priced=False` mimics Massive, where a
    new ticker has no price until the next poll.
    """

    def __init__(self, cache: PriceCache, prices: dict[str, float] | None = None, priced=True):
        self.cache = cache
        self.prices = prices if prices is not None else {}
        self.priced = priced
        self.tickers: list[str] = []
        self.started = False
        self.stopped = False

    async def start(self, tickers: list[str]) -> None:
        self.started = True
        for ticker in tickers:
            await self.add_ticker(ticker)

    async def stop(self) -> None:
        self.stopped = True

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        if ticker not in self.tickers:
            self.tickers.append(ticker)
            if self.priced:
                self.cache.update(ticker, self.prices.get(ticker, 100.0))

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        if ticker in self.tickers:
            self.tickers.remove(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self.tickers)


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "finally.db")
    db.init_db(path)
    return path


@pytest.fixture
def price_cache() -> PriceCache:
    return PriceCache()


@pytest.fixture
async def app_state(db_path, price_cache) -> AppState:
    """AppState over a seeded temp DB and a started FakeSource (all tickers at $100)."""
    source = FakeSource(price_cache)
    with closing(db.connect(db_path)) as conn:
        tickers = [e["ticker"] for e in db.list_watchlist(conn)]
    await source.start(tickers)
    return AppState(db_path=db_path, price_cache=price_cache, market_source=source)


@pytest.fixture
def api_client(tmp_path):
    """TestClient (lifespan running) over a temp DB, FakeSource and no static dir."""
    from app.main import create_app

    sources: list[FakeSource] = []

    def factory(cache: PriceCache) -> FakeSource:
        sources.append(FakeSource(cache, {"AAPL": 190.0, "NVDA": 800.0}))
        return sources[0]

    app = create_app(
        db_path=str(tmp_path / "api.db"),
        static_dir=str(tmp_path / "no-static"),
        source_factory=factory,
    )
    with TestClient(app) as client:
        client.source = sources[0]
        yield client

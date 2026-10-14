"""Tests for the SSE generator and the price-history endpoint."""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class FakeRequest:
    """Reports a disconnect after `checks` successful is_disconnected() calls."""

    client = None

    def __init__(self, checks: int, on_check=None):
        self.left = checks
        self.on_check = on_check  # called with the 0-based check number while connected
        self.n = 0

    async def is_disconnected(self) -> bool:
        if self.left <= 0:
            return True
        if self.on_check:
            self.on_check(self.n)
        self.n += 1
        self.left -= 1
        return False


async def collect(cache, request, **kwargs) -> list[str]:
    kwargs.setdefault("interval", 0)
    return [frame async for frame in _generate_events(cache, request, **kwargs)]


def parse(frame: str) -> dict:
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    return json.loads(frame[len("data: ") :])


class TestGenerateEvents:
    async def test_retry_then_data(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        frames = await collect(cache, FakeRequest(1))
        assert frames[0] == "retry: 1000\n\n"
        assert parse(frames[1])["AAPL"]["price"] == 190.0

    async def test_frame_has_all_tickers_and_plan_fields(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("MSFT", 420.0)
        data = parse((await collect(cache, FakeRequest(1)))[1])
        assert set(data) == {"AAPL", "MSFT"}
        assert set(data["AAPL"]) == {
            "ticker",
            "price",
            "previous_price",
            "open_price",
            "timestamp",
            "change",
            "change_percent",
            "direction",
        }

    async def test_no_frame_without_change(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        frames = await collect(cache, FakeRequest(3), keepalive=999)
        assert len(frames) == 2  # retry + one data frame

    async def test_frame_per_change(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        request = FakeRequest(3, on_check=lambda n: n == 1 and cache.update("AAPL", 191.0))
        frames = await collect(cache, request, keepalive=999)
        assert [parse(f)["AAPL"]["price"] for f in frames[1:]] == [190.0, 191.0]

    async def test_removal_sends_frame_without_ticker(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("MSFT", 420.0)
        request = FakeRequest(3, on_check=lambda n: n == 1 and cache.remove("MSFT"))
        frames = await collect(cache, request, keepalive=999)
        assert [set(parse(f)) for f in frames[1:]] == [{"AAPL", "MSFT"}, {"AAPL"}]

    async def test_empty_cache_sends_empty_frame(self):
        frames = await collect(PriceCache(), FakeRequest(1))
        assert frames == ["retry: 1000\n\n", "data: {}\n\n"]

    async def test_keepalive_when_idle(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        frames = await collect(cache, FakeRequest(3), keepalive=0)
        assert frames[2:] == [": keep-alive\n\n", ": keep-alive\n\n"]

    async def test_immediate_disconnect(self):
        assert await collect(PriceCache(), FakeRequest(0)) == ["retry: 1000\n\n"]

    async def test_cancellation_propagates(self):
        """CancelledError is not swallowed, so task cancellation completes normally."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        async def consume():
            async for _ in _generate_events(cache, FakeRequest(10**6), interval=10):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestHistoryEndpoint:
    def _client(self, cache):
        app = FastAPI()
        app.include_router(create_stream_router(cache))
        return TestClient(app)

    def test_returns_points(self):
        cache = PriceCache(clock=lambda: 1760000000.5)
        cache.update("AAPL", 190.41, timestamp=1760000000.0)
        cache.update("AAPL", 190.52, timestamp=1760000000.5)
        body = self._client(cache).get("/api/prices/AAPL/history").json()
        assert body == {
            "ticker": "AAPL",
            "points": [
                {"timestamp": 1760000000.0, "price": 190.41},
                {"timestamp": 1760000000.5, "price": 190.52},
            ],
        }

    def test_lowercase_ticker_normalised(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        body = self._client(cache).get("/api/prices/aapl/history").json()
        assert body["ticker"] == "AAPL"
        assert len(body["points"]) == 1

    def test_untracked_ticker_is_empty_200(self):
        resp = self._client(PriceCache()).get("/api/prices/ZZZ/history")
        assert resp.status_code == 200
        assert resp.json() == {"ticker": "ZZZ", "points": []}


class TestRouterFactory:
    def test_routers_are_independent(self):
        a, b = create_stream_router(PriceCache()), create_stream_router(PriceCache())
        assert len(a.routes) == len(b.routes) == 2

    def test_route_paths(self):
        router = create_stream_router(PriceCache())
        paths = {route.path for route in router.routes}
        assert paths == {"/api/stream/prices", "/api/prices/{ticker}/history"}

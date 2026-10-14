"""Tests for the PLAN §6 [change] items: session open, history buffer, poll interval, history API."""

import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.market.cache import HISTORY_SIZE, PriceCache
from app.market.factory import create_market_data_source
from app.market.models import PriceUpdate
from app.market.stream import create_stream_router


class TestSessionOpen:
    def test_open_price_is_first_price(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("AAPL", 191.00)
        update = cache.update("AAPL", 189.00)
        assert update.open_price == 190.00

    def test_open_price_per_ticker(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        cache.update("AAPL", 195.00)
        assert cache.get("GOOGL").open_price == 175.00
        assert cache.get("AAPL").open_price == 190.00

    def test_remove_resets_open_price(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.update("AAPL", 200.00).open_price == 200.00

    def test_to_dict_includes_open_price(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        d = cache.update("AAPL", 191.00).to_dict()
        assert d["open_price"] == 190.00

    def test_to_dict_open_price_defaults_to_price(self):
        update = PriceUpdate(ticker="AAPL", price=10.0, previous_price=10.0)
        assert update.to_dict()["open_price"] == 10.0


class TestHistory:
    def test_empty_for_unknown_ticker(self):
        assert PriceCache().get_history("NOPE") == []

    def test_points_in_order(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, timestamp=1.0)
        cache.update("AAPL", 191.0, timestamp=2.0)
        assert cache.get_history("AAPL") == [(1.0, 190.0), (2.0, 191.0)]

    def test_ring_buffer_caps_at_600(self):
        cache = PriceCache()
        for i in range(HISTORY_SIZE + 50):
            cache.update("AAPL", 100.0 + i * 0.01, timestamp=float(i + 1))
        history = cache.get_history("AAPL")
        assert len(history) == HISTORY_SIZE == 600
        assert history[0][0] == 51.0  # oldest 50 dropped
        assert history[-1][0] == float(HISTORY_SIZE + 50)

    def test_get_history_returns_copy(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, timestamp=1.0)
        cache.get_history("AAPL").clear()
        assert len(cache.get_history("AAPL")) == 1

    def test_remove_clears_history(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.remove("AAPL")
        assert cache.get_history("AAPL") == []


class TestPollInterval:
    def _make(self, env):
        with patch.dict(os.environ, {"MASSIVE_API_KEY": "k", **env}, clear=True):
            return create_market_data_source(PriceCache())

    def test_default_is_15(self):
        assert self._make({})._interval == 15.0

    def test_env_var_respected(self):
        assert self._make({"MASSIVE_POLL_INTERVAL": "5"})._interval == 5.0

    def test_float_value(self):
        assert self._make({"MASSIVE_POLL_INTERVAL": "2.5"})._interval == 2.5

    def test_empty_uses_default(self):
        assert self._make({"MASSIVE_POLL_INTERVAL": ""})._interval == 15.0

    def test_invalid_uses_default(self):
        assert self._make({"MASSIVE_POLL_INTERVAL": "abc"})._interval == 15.0

    def test_non_positive_uses_default(self):
        assert self._make({"MASSIVE_POLL_INTERVAL": "0"})._interval == 15.0
        assert self._make({"MASSIVE_POLL_INTERVAL": "-3"})._interval == 15.0


class TestHistoryEndpoint:
    def _client(self, cache):
        app = FastAPI()
        app.include_router(create_stream_router(cache))
        return TestClient(app)

    def test_returns_points(self):
        cache = PriceCache()
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
        cache.update("AAPL", 190.0, timestamp=1.0)
        body = self._client(cache).get("/api/prices/aapl/history").json()
        assert body["ticker"] == "AAPL"
        assert len(body["points"]) == 1

    def test_untracked_ticker_is_empty_200(self):
        resp = self._client(PriceCache()).get("/api/prices/ZZZ/history")
        assert resp.status_code == 200
        assert resp.json() == {"ticker": "ZZZ", "points": []}

    def test_router_can_be_created_twice(self):
        # Routers are built per call, so routes must not accumulate across calls
        create_stream_router(PriceCache())
        router = create_stream_router(PriceCache())
        assert len(router.routes) == 2

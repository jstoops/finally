"""Tests for market data source factory."""

import os
from unittest.mock import patch

from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource


class TestFactory:
    """Tests for create_market_data_source factory."""

    def test_creates_simulator_when_no_api_key(self):
        """Test that simulator is created when MASSIVE_API_KEY is not set."""
        cache = PriceCache()

        with patch.dict(os.environ, {}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_simulator_when_api_key_empty(self):
        """Test that simulator is created when MASSIVE_API_KEY is empty."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": ""}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_simulator_when_api_key_whitespace(self):
        """Test that simulator is created when MASSIVE_API_KEY is whitespace."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "   "}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_massive_when_api_key_set(self):
        """Test that Massive client is created when MASSIVE_API_KEY is set."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)

    def test_massive_receives_api_key(self):
        """Test that Massive client receives the API key."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key-123"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)
        assert source._api_key == "test-key-123"

    def test_simulator_receives_cache(self):
        """Test that simulator receives the cache reference."""
        cache = PriceCache()

        with patch.dict(os.environ, {}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)
        assert source._cache is cache

    def test_massive_receives_cache(self):
        """Test that Massive client receives the cache reference."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)
        assert source._cache is cache


class TestPollInterval:
    """MASSIVE_POLL_INTERVAL parsing (PLAN §5)."""

    def _interval(self, env):
        with patch.dict(os.environ, {"MASSIVE_API_KEY": "k", **env}, clear=True):
            return create_market_data_source(PriceCache())._interval

    def test_default_is_15(self):
        assert self._interval({}) == 15.0

    def test_env_var_respected(self):
        assert self._interval({"MASSIVE_POLL_INTERVAL": "5"}) == 5.0

    def test_float_value(self):
        assert self._interval({"MASSIVE_POLL_INTERVAL": "2.5"}) == 2.5

    def test_blank_uses_default(self):
        assert self._interval({"MASSIVE_POLL_INTERVAL": ""}) == 15.0
        assert self._interval({"MASSIVE_POLL_INTERVAL": "  "}) == 15.0

    def test_invalid_uses_default(self):
        assert self._interval({"MASSIVE_POLL_INTERVAL": "fast"}) == 15.0

    def test_nan_and_infinity_use_default(self):
        """NaN would crash asyncio.sleep(); infinity would never poll."""
        for raw in ("nan", "inf", "-inf", "Infinity"):
            assert self._interval({"MASSIVE_POLL_INTERVAL": raw}) == 15.0

    def test_below_minimum_is_clamped_to_1(self):
        for raw in ("0.2", "0", "-3"):
            assert self._interval({"MASSIVE_POLL_INTERVAL": raw}) == 1.0

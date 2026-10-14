"""Tests for PriceCache."""

from app.market.cache import PriceCache


class TestPriceCache:
    """Unit tests for the PriceCache."""

    def test_update_and_get(self):
        """Test updating and getting a price."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.ticker == "AAPL"
        assert update.price == 190.50
        assert cache.get("AAPL") == update

    def test_first_update_is_flat(self):
        """Test that the first update has flat direction."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.direction == "flat"
        assert update.previous_price == 190.50

    def test_direction_up(self):
        """Test price update with upward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 191.00)
        assert update.direction == "up"
        assert update.change == 1.00

    def test_direction_down(self):
        """Test price update with downward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 189.00)
        assert update.direction == "down"
        assert update.change == -1.00

    def test_remove(self):
        """Test removing a ticker from cache."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get("AAPL") is None

    def test_remove_nonexistent(self):
        """Test removing a ticker that doesn't exist."""
        cache = PriceCache()
        cache.remove("AAPL")  # Should not raise

    def test_get_all(self):
        """Test getting all prices."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        all_prices = cache.get_all()
        assert set(all_prices.keys()) == {"AAPL", "GOOGL"}

    def test_version_increments(self):
        """Test that version counter increments."""
        cache = PriceCache()
        v0 = cache.version
        cache.update("AAPL", 190.00)
        assert cache.version == v0 + 1
        cache.update("AAPL", 191.00)
        assert cache.version == v0 + 2

    def test_get_price_convenience(self):
        """Test the convenience get_price method."""
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("NOPE") is None

    def test_len(self):
        """Test __len__ method."""
        cache = PriceCache()
        assert len(cache) == 0
        cache.update("AAPL", 190.00)
        assert len(cache) == 1
        cache.update("GOOGL", 175.00)
        assert len(cache) == 2

    def test_contains(self):
        """Test __contains__ method."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert "AAPL" in cache
        assert "GOOGL" not in cache

    def test_custom_timestamp(self):
        """Test updating with a custom timestamp."""
        cache = PriceCache()
        custom_ts = 1234567890.0
        update = cache.update("AAPL", 190.50, timestamp=custom_ts)
        assert update.timestamp == custom_ts

    def test_price_rounding(self):
        """Test that prices are rounded to 2 decimal places."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.12345)
        assert update.price == 190.12


class FakeClock:
    """Controllable replacement for time.time()."""

    def __init__(self, t: float = 1_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestSessionOpen:
    """open_price: first price seen per ticker, carried forward (PLAN §6)."""

    def test_open_price_is_first_price(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("AAPL", 191.00)
        update = cache.update("AAPL", 189.00)
        assert update.open_price == 190.00
        assert update.previous_price == 191.00
        assert update.session_change_percent == round((189 - 190) / 190 * 100, 4)

    def test_open_price_per_ticker(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        cache.update("AAPL", 195.00)
        assert cache.get("GOOGL").open_price == 175.00
        assert cache.get("AAPL").open_price == 190.00

    def test_open_price_is_rounded(self):
        assert PriceCache().update("AAPL", 190.126).open_price == 190.13

    def test_remove_starts_new_session(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.update("AAPL", 200.00).open_price == 200.00

    def test_to_dict_includes_open_price(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert cache.update("AAPL", 191.00).to_dict()["open_price"] == 190.00


class TestHistory:
    """Per-ticker history buffer: last 5 minutes, at most 600 points."""

    def test_empty_for_unknown_ticker(self):
        assert PriceCache().get_history("NOPE") == []

    def test_points_in_order(self):
        clock = FakeClock()
        cache = PriceCache(clock=clock)
        cache.update("AAPL", 190.0)
        clock.t += 0.5
        cache.update("AAPL", 191.0)
        points = cache.get_history("AAPL")
        assert [(p.timestamp, p.price) for p in points] == [(1000.0, 190.0), (1000.5, 191.0)]

    def test_count_limit(self):
        clock = FakeClock()
        cache = PriceCache(history_max_points=5, clock=clock)
        for i in range(10):
            clock.t += 0.5
            cache.update("AAPL", 100.0 + i)
        assert [p.price for p in cache.get_history("AAPL")] == [105.0, 106.0, 107.0, 108.0, 109.0]

    def test_default_count_limit_is_600(self):
        clock = FakeClock()
        cache = PriceCache(clock=clock)
        for i in range(650):
            clock.t += 0.1  # 65 s in total, all within the age limit
            cache.update("AAPL", 100.0 + i * 0.01)
        assert len(cache.get_history("AAPL")) == 600 == PriceCache.HISTORY_MAX_POINTS

    def test_age_limit(self):
        """Slow sources (Massive, 15 s polls) still serve only the last ~5 minutes."""
        clock = FakeClock()
        cache = PriceCache(clock=clock)
        cache.update("AAPL", 1.0)  # t=1000
        clock.t += 301
        cache.update("AAPL", 2.0)  # t=1301
        assert [p.price for p in cache.get_history("AAPL")] == [2.0]

    def test_returns_copy(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.get_history("AAPL").clear()
        assert len(cache.get_history("AAPL")) == 1

    def test_remove_clears_history(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.remove("AAPL")
        assert cache.get_history("AAPL") == []


class TestTimestamps:
    def test_default_is_clock(self):
        assert PriceCache(clock=FakeClock(42.0)).update("AAPL", 1.0).timestamp == 42.0

    def test_strictly_increasing(self):
        """Repeated or backwards timestamps are nudged forward (charts need ascending time)."""
        cache = PriceCache(clock=FakeClock(60.0))
        a = cache.update("AAPL", 1.0, timestamp=50.0)
        b = cache.update("AAPL", 1.0, timestamp=50.0)  # repeated
        c = cache.update("AAPL", 1.0, timestamp=10.0)  # clock stepped back
        assert a.timestamp < b.timestamp < c.timestamp
        history = [p.timestamp for p in cache.get_history("AAPL")]
        assert len(history) == 3
        assert history == sorted(set(history))

    def test_increasing_per_ticker_only(self):
        cache = PriceCache()
        cache.update("AAPL", 1.0, timestamp=50.0)
        assert cache.update("MSFT", 1.0, timestamp=50.0).timestamp == 50.0

    def test_zero_is_respected(self):
        assert PriceCache().update("AAPL", 1.0, timestamp=0.0).timestamp == 0.0


class TestVersionOnRemove:
    def test_remove_bumps_version_only_if_present(self):
        cache = PriceCache()
        cache.update("AAPL", 1.0)
        v = cache.version
        cache.remove("AAPL")
        assert cache.version == v + 1
        cache.remove("AAPL")
        assert cache.version == v + 1

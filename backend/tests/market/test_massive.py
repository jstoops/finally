"""Tests for MassiveDataSource.

Fixtures use the REAL massive model classes (TickerSnapshot.from_dict etc.).
A MagicMock snapshot would "have" any attribute, which is how a read of the
non-existent last_trade.timestamp once went unnoticed. The REST client itself
is a MagicMock, injected through the constructor.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from massive.exceptions import BadResponse
from massive.rest.models import GroupedDailyAgg, PreviousCloseAgg, TickerSnapshot

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource, is_not_entitled, pick_price

NOT_ENTITLED = '{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data."}'
BAD_KEY = '{"status":"ERROR","error":"Unknown API Key"}'


def snap(ticker, *, trade=None, minute=None, day=None, prev=None) -> TickerSnapshot:
    """Build a snapshot from the wire format, exactly as the client would."""
    data = {"ticker": ticker}
    if trade is not None:
        data["lastTrade"] = {"p": trade, "t": 1_760_000_000_000_000_000}  # ns
    if minute is not None:
        data["min"] = {"c": minute}
    if day is not None:
        data["day"] = {"c": day}
    if prev is not None:
        data["prevDay"] = {"c": prev}
    return TickerSnapshot.from_dict(data)


def source_with(client, **kwargs) -> tuple[MassiveDataSource, PriceCache]:
    cache = PriceCache()
    return MassiveDataSource("k", cache, poll_interval=60, client=client, **kwargs), cache


class TestPickPrice:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"trade": 190.5, "minute": 190.4, "day": 190.3, "prev": 189.0}, 190.5),
            ({"minute": 190.4, "day": 190.3, "prev": 189.0}, 190.4),
            ({"day": 190.3, "prev": 189.0}, 190.3),
            ({"day": 0, "prev": 189.0}, 189.0),  # day bar zeroed overnight
            ({"trade": 0, "prev": 189.0}, 189.0),
            ({}, None),
        ],
    )
    def test_fallback_order(self, kwargs, expected):
        assert pick_price(snap("AAPL", **kwargs)) == expected


class TestIsNotEntitled:
    def test_not_authorized(self):
        assert is_not_entitled(BadResponse(NOT_ENTITLED))

    def test_bad_key_is_not_entitlement(self):
        assert not is_not_entitled(BadResponse(BAD_KEY))


class TestLiveMode:
    async def test_real_snapshot_updates_cache(self):
        """Regression: a real LastTrade has no `timestamp` attribute."""
        client = MagicMock()
        client.get_snapshot_all.return_value = [
            snap("AAPL", trade=190.5),
            snap("MSFT", prev=420.0),
        ]
        source, cache = source_with(client)
        await source.start(["AAPL", "MSFT"])
        try:
            assert cache.get_price("AAPL") == 190.5
            assert cache.get_price("MSFT") == 420.0
            assert source.mode == "live"
        finally:
            await source.stop()

    async def test_uses_receipt_time_not_exchange_time(self):
        client = MagicMock()
        client.get_snapshot_all.return_value = [snap("AAPL", trade=190.5)]
        cache = PriceCache(clock=lambda: 1234.5)
        source = MassiveDataSource("k", cache, client=client)
        source._tickers = ["AAPL"]
        await source._poll_once()
        assert cache.get("AAPL").timestamp == 1234.5  # not the trade's 1.76e9 s

    async def test_repeated_polls_give_ascending_history(self):
        """Same trade returned twice (no new trade) still yields distinct, ascending times."""
        client = MagicMock()
        client.get_snapshot_all.return_value = [snap("AAPL", trade=190.5)]
        source, cache = source_with(client)
        source._tickers = ["AAPL"]
        await source._poll_once()
        await source._poll_once()
        times = [p.timestamp for p in cache.get_history("AAPL")]
        assert len(times) == 2 and times[0] < times[1]

    async def test_one_call_for_all_tickers_uppercase(self):
        client = MagicMock()
        client.get_snapshot_all.return_value = []
        source, _ = source_with(client)
        await source.start(["aapl", " msft ", "AAPL"])
        try:
            assert client.get_snapshot_all.call_count == 1
            assert client.get_snapshot_all.call_args.kwargs["tickers"] == ["AAPL", "MSFT"]
        finally:
            await source.stop()

    async def test_snapshot_without_price_is_skipped(self):
        client = MagicMock()
        client.get_snapshot_all.return_value = [snap("AAPL", trade=190.5), snap("BAD")]
        source, cache = source_with(client)
        source._tickers = ["AAPL", "BAD"]
        await source._poll_once()
        assert cache.get_price("AAPL") == 190.5
        assert "BAD" not in cache

    async def test_missing_ticker_warned_once(self, caplog):
        client = MagicMock()
        client.get_snapshot_all.return_value = []
        source, _ = source_with(client)
        source._tickers = ["ZZZZ"]
        await source._poll_once()
        await source._poll_once()
        assert sum("no price for ZZZZ" in r.message for r in caplog.records) == 1

    async def test_bad_key_stays_live_and_does_not_raise(self):
        client = MagicMock()
        client.get_snapshot_all.side_effect = BadResponse(BAD_KEY)
        source, cache = source_with(client)
        await source.start(["AAPL"])
        try:
            assert source.mode == "live"
            assert cache.get_price("AAPL") is None
            assert source._task is not None and not source._task.done()
        finally:
            await source.stop()

    async def test_network_error_does_not_raise(self):
        client = MagicMock()
        client.get_snapshot_all.side_effect = ConnectionError("down")
        source, cache = source_with(client)
        source._tickers = ["AAPL"]
        await source._poll_once()
        assert len(cache) == 0

    async def test_ticker_removed_mid_poll_is_not_written(self):
        """Regression: a removal during the HTTP call must not resurrect the ticker."""
        client = MagicMock()
        source, cache = source_with(client)
        source._tickers = ["AAPL", "TSLA"]

        def fetch(market_type, tickers):
            source._tickers.remove("TSLA")  # what remove_ticker does, mid-call
            return [snap("AAPL", trade=1.0), snap("TSLA", trade=2.0)]

        client.get_snapshot_all.side_effect = fetch
        await source._poll_once()
        assert "AAPL" in cache
        assert "TSLA" not in cache

    async def test_worker_thread_gets_a_copy_of_tickers(self):
        client = MagicMock()
        client.get_snapshot_all.return_value = []
        source, _ = source_with(client)
        source._tickers = ["AAPL"]
        await source._poll_once()
        assert client.get_snapshot_all.call_args.kwargs["tickers"] is not source._tickers

    async def test_no_tickers_skips_poll(self):
        client = MagicMock()
        source, _ = source_with(client)
        await source._poll_once()
        client.get_snapshot_all.assert_not_called()


class TestEodMode:
    def _client(self, grouped):
        client = MagicMock()
        client.get_snapshot_all.side_effect = BadResponse(NOT_ENTITLED)
        client.get_grouped_daily_aggs.return_value = grouped
        return client

    async def test_not_entitled_switches_to_eod_once(self):
        client = self._client(
            [
                GroupedDailyAgg(ticker="AAPL", close=190.0),
                GroupedDailyAgg(ticker="PYPL", close=70.0),
            ]
        )
        source, cache = source_with(client)
        await source.start(["AAPL"])
        try:
            assert source.mode == "eod"
            assert cache.get_price("AAPL") == 190.0
            await source.add_ticker("PYPL")
            await source._poll_once()  # served from memory: no new grouped call
            assert cache.get_price("PYPL") == 70.0
            assert client.get_snapshot_all.call_count == 1
            assert client.get_grouped_daily_aggs.call_count == 1
        finally:
            await source.stop()

    async def test_walks_back_to_latest_trading_day_skipping_weekends(self):
        client = self._client(None)
        # Empty for the first weekday tried (data not published yet), then data
        client.get_grouped_daily_aggs.side_effect = [
            [],
            [GroupedDailyAgg(ticker="AAPL", close=189.0)],
        ]
        source, cache = source_with(client)

        class Saturday(date):
            @classmethod
            def today(cls):
                return date(2026, 10, 10)  # Saturday

        with patch("app.market.massive_client.date", Saturday):
            await source.start(["AAPL"])
        try:
            days = [c.args[0] for c in client.get_grouped_daily_aggs.call_args_list]
            assert days == ["2026-10-09", "2026-10-08"]  # Fri (empty), Thu; no weekend calls
            assert cache.get_price("AAPL") == 189.0
        finally:
            await source.stop()

    async def test_missing_ticker_uses_previous_close(self):
        client = self._client([GroupedDailyAgg(ticker="AAPL", close=190.0)])
        client.get_previous_close_agg.return_value = [PreviousCloseAgg(ticker="BRK.B", close=450.0)]
        source, cache = source_with(client)
        await source.start(["AAPL", "BRK.B"])
        try:
            assert cache.get_price("BRK.B") == 450.0
            client.get_previous_close_agg.assert_called_once_with("BRK.B")
        finally:
            await source.stop()

    async def test_unknown_ticker_not_retried_every_poll(self):
        client = self._client([GroupedDailyAgg(ticker="AAPL", close=190.0)])
        client.get_previous_close_agg.return_value = []
        source, cache = source_with(client)
        await source.start(["AAPL", "ZZZZ"])
        try:
            await source._poll_once()
            await source._poll_once()
            assert client.get_previous_close_agg.call_count == 1
            assert "ZZZZ" not in cache
        finally:
            await source.stop()

    async def test_previous_close_calls_are_capped_per_poll(self):
        client = self._client([GroupedDailyAgg(ticker="AAPL", close=190.0)])
        client.get_previous_close_agg.return_value = []
        source, _ = source_with(client)
        source._mode = "eod"
        source._tickers = ["AAPL", "X1", "X2", "X3", "X4"]
        await source._poll_once()
        assert client.get_previous_close_agg.call_count == MassiveDataSource.EOD_PREV_CLOSE_PER_POLL

    async def test_grouped_data_refreshed_hourly_not_per_poll(self):
        client = self._client([GroupedDailyAgg(ticker="AAPL", close=190.0)])
        source, _ = source_with(client)
        source._mode = "eod"
        source._tickers = ["AAPL"]
        with patch("app.market.massive_client.time.time", return_value=10_000.0):
            await source._poll_once()
            await source._poll_once()
        assert client.get_grouped_daily_aggs.call_count == 1
        with patch("app.market.massive_client.time.time", return_value=10_000.0 + 3601):
            await source._poll_once()
        assert client.get_grouped_daily_aggs.call_count == 2


class TestTickerManagement:
    async def test_add_ticker_normalizes(self):
        source, _ = source_with(MagicMock())
        await source.add_ticker("  aapl ")
        await source.add_ticker("AAPL")
        assert source.get_tickers() == ["AAPL"]

    async def test_remove_ticker_clears_cache(self):
        source, cache = source_with(MagicMock())
        source._tickers = ["AAPL", "GOOGL"]
        cache.update("AAPL", 190.00)
        await source.remove_ticker("aapl")
        assert source.get_tickers() == ["GOOGL"]
        assert cache.get("AAPL") is None

    async def test_start_creates_client_with_key(self):
        source = MassiveDataSource("secret", PriceCache(), poll_interval=60)
        with patch("app.market.massive_client.RESTClient") as rest:
            rest.return_value.get_snapshot_all.return_value = []
            await source.start(["AAPL"])
        try:
            rest.assert_called_once_with(api_key="secret")
        finally:
            await source.stop()

    async def test_stop_is_idempotent(self):
        source, _ = source_with(MagicMock())
        await source.stop()
        await source.stop()

    async def test_stop_cancels_task(self):
        client = MagicMock()
        client.get_snapshot_all.return_value = []
        source, _ = source_with(client)
        await source.start(["AAPL"])
        assert source._task is not None and not source._task.done()
        await source.stop()
        assert source._task is None

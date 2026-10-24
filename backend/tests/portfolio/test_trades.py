"""Trade rules (PLAN §7) and tracked tickers (PLAN §6)."""

from contextlib import closing

import pytest

from app import db
from app.portfolio import (
    TradeError,
    add_to_watchlist,
    build_portfolio,
    execute_trade,
    normalize_ticker,
    remove_from_watchlist,
    reset_account,
)


def _conn(state):
    return closing(state.connect())


def _cash(state) -> float:
    with _conn(state) as conn:
        return db.get_cash(conn)


def _position(state, ticker):
    with _conn(state) as conn:
        return db.get_position(conn, ticker)


def _snapshots(state):
    with _conn(state) as conn:
        return db.list_snapshots(conn)


class TestNormalizeTicker:
    @pytest.mark.parametrize(
        "raw,expected",
        [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("X", "X"), ("A123456789", "A123456789")],
    )
    def test_valid(self, raw, expected):
        assert normalize_ticker(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "1ABC", ".A", "AB-C", "ABCDEFGHIJK", "AA PL", "$X"])
    def test_invalid(self, raw):
        with pytest.raises(TradeError, match="Invalid ticker"):
            normalize_ticker(raw)


class TestBuy:
    async def test_buy_debits_cash_and_creates_position(self, app_state):
        trade = await execute_trade(app_state, " aapl ", "buy", 10)
        assert trade["ticker"] == "AAPL"
        assert trade["side"] == "buy"
        assert trade["quantity"] == 10
        assert trade["price"] == 100.0
        assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
        assert _cash(app_state) == pytest.approx(9000.0)
        pos = _position(app_state, "AAPL")
        assert pos["quantity"] == 10
        assert pos["avg_cost"] == 100.0

    async def test_buy_averages_cost(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 10)
        app_state.price_cache.update("AAPL", 130.0)
        await execute_trade(app_state, "AAPL", "buy", 5)
        pos = _position(app_state, "AAPL")
        assert pos["quantity"] == 15
        assert pos["avg_cost"] == pytest.approx((10 * 100 + 5 * 130) / 15)

    async def test_insufficient_cash(self, app_state):
        with pytest.raises(TradeError) as exc:
            await execute_trade(app_state, "AAPL", "buy", 101)
        assert str(exc.value) == "Insufficient cash (need $10,100.00, have $10,000.00)"
        assert _cash(app_state) == 10000.0
        assert _position(app_state, "AAPL") is None

    async def test_buy_exactly_all_cash(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 100)
        assert _cash(app_state) == pytest.approx(0.0)

    async def test_fractional_quantity_rounded_to_4dp(self, app_state):
        trade = await execute_trade(app_state, "AAPL", "buy", 1.234567)
        assert trade["quantity"] == 1.2346
        assert _cash(app_state) == pytest.approx(10000 - 123.46)


class TestValidation:
    @pytest.mark.parametrize("qty", [0, -1, 0.00001, float("nan"), float("inf")])
    async def test_bad_quantity(self, app_state, qty):
        with pytest.raises(TradeError, match="Quantity"):
            await execute_trade(app_state, "AAPL", "buy", qty)

    async def test_bad_side(self, app_state):
        with pytest.raises(TradeError, match="Side must be"):
            await execute_trade(app_state, "AAPL", "hold", 1)

    async def test_side_case_insensitive(self, app_state):
        trade = await execute_trade(app_state, "AAPL", "BUY", 1)
        assert trade["side"] == "buy"

    async def test_malformed_ticker(self, app_state):
        with pytest.raises(TradeError, match="Invalid ticker"):
            await execute_trade(app_state, "12$", "buy", 1)

    async def test_no_cached_price(self, app_state):
        with pytest.raises(TradeError) as exc:
            await execute_trade(app_state, "zzz", "buy", 1)
        assert str(exc.value) == "No price available for ZZZ. Add it to your watchlist first."

    async def test_failed_trade_records_nothing(self, app_state):
        with pytest.raises(TradeError):
            await execute_trade(app_state, "AAPL", "sell", 1)
        assert _snapshots(app_state) == []
        assert _cash(app_state) == 10000.0


class TestSell:
    async def test_sell_credits_cash_keeps_avg_cost(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 10)
        app_state.price_cache.update("AAPL", 120.0)
        await execute_trade(app_state, "AAPL", "sell", 4)
        assert _cash(app_state) == pytest.approx(9000 + 480)
        pos = _position(app_state, "AAPL")
        assert pos["quantity"] == 6
        assert pos["avg_cost"] == 100.0

    async def test_sell_at_a_loss(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 10)
        app_state.price_cache.update("AAPL", 80.0)
        await execute_trade(app_state, "AAPL", "sell", 10)
        assert _cash(app_state) == pytest.approx(9800.0)
        assert _position(app_state, "AAPL") is None

    async def test_sell_more_than_owned(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 2)
        with pytest.raises(TradeError) as exc:
            await execute_trade(app_state, "AAPL", "sell", 5)
        assert str(exc.value) == "Insufficient shares of AAPL (have 2, trying to sell 5)"
        assert _position(app_state, "AAPL")["quantity"] == 2

    async def test_sell_without_position(self, app_state):
        with pytest.raises(TradeError, match="have 0"):
            await execute_trade(app_state, "AAPL", "sell", 1)

    async def test_dust_position_removed(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 1.0001)
        with _conn(app_state) as conn:
            db.upsert_position(conn, "AAPL", 1.0000004, 100.0)  # float drift
        await execute_trade(app_state, "AAPL", "sell", 1)
        assert _position(app_state, "AAPL") is None
        with _conn(app_state) as conn:
            assert build_portfolio(conn, app_state.price_cache)["positions"] == []

    async def test_sell_within_tolerance_allowed(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 1)
        with _conn(app_state) as conn:
            db.upsert_position(conn, "AAPL", 0.9999995, 100.0)
        await execute_trade(app_state, "AAPL", "sell", 1)
        assert _position(app_state, "AAPL") is None


class TestSnapshotsAndTradeLog:
    async def test_snapshot_after_each_trade(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 1)
        await execute_trade(app_state, "AAPL", "sell", 1)
        snaps = _snapshots(app_state)
        assert len(snaps) == 2
        assert snaps[-1]["total_value"] == pytest.approx(10000.0)

    async def test_trades_logged(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 3)
        await execute_trade(app_state, "AAPL", "sell", 1)
        with _conn(app_state) as conn:
            rows = conn.execute("SELECT side, quantity FROM trades ORDER BY rowid").fetchall()
        assert [tuple(r) for r in rows] == [("buy", 3), ("sell", 1)]


class TestTrackedTickers:
    async def test_watchlist_add_starts_pricing(self, app_state):
        entry, created = await add_to_watchlist(app_state, " pypl ")
        assert created
        assert entry["ticker"] == "PYPL"
        assert "PYPL" in app_state.market_source.get_tickers()
        assert app_state.price_cache.get_price("PYPL") == 100.0

    async def test_watchlist_add_idempotent(self, app_state):
        _, created = await add_to_watchlist(app_state, "AAPL")
        assert not created

    async def test_watchlist_add_malformed(self, app_state):
        with pytest.raises(TradeError):
            await add_to_watchlist(app_state, "bad ticker")

    async def test_remove_unheld_stops_pricing(self, app_state):
        assert await remove_from_watchlist(app_state, "GOOGL")
        assert "GOOGL" not in app_state.market_source.get_tickers()
        assert app_state.price_cache.get_price("GOOGL") is None

    async def test_remove_held_keeps_pricing(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 1)
        assert await remove_from_watchlist(app_state, "AAPL")
        assert "AAPL" in app_state.market_source.get_tickers()
        assert app_state.price_cache.get_price("AAPL") == 100.0

    async def test_remove_missing_returns_false(self, app_state):
        assert not await remove_from_watchlist(app_state, "PYPL")

    async def test_sell_to_zero_drops_unwatched_ticker(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 2)
        await remove_from_watchlist(app_state, "AAPL")
        await execute_trade(app_state, "AAPL", "sell", 1)
        assert "AAPL" in app_state.market_source.get_tickers()
        await execute_trade(app_state, "AAPL", "sell", 1)
        assert "AAPL" not in app_state.market_source.get_tickers()
        assert app_state.price_cache.get_price("AAPL") is None

    async def test_sell_to_zero_keeps_watched_ticker(self, app_state):
        await execute_trade(app_state, "AAPL", "buy", 1)
        await execute_trade(app_state, "AAPL", "sell", 1)
        assert "AAPL" in app_state.market_source.get_tickers()


class TestReset:
    async def test_reset_restores_seed_state(self, app_state):
        await add_to_watchlist(app_state, "PYPL")
        await remove_from_watchlist(app_state, "GOOGL")
        await execute_trade(app_state, "PYPL", "buy", 5)
        await remove_from_watchlist(app_state, "PYPL")
        with _conn(app_state) as conn:
            db.insert_chat_message(conn, "user", "hi")

        await reset_account(app_state)

        with _conn(app_state) as conn:
            assert db.get_cash(conn) == 10000.0
            assert db.list_positions(conn) == []
            assert [e["ticker"] for e in db.list_watchlist(conn)] == db.DEFAULT_WATCHLIST
            assert db.list_chat_messages(conn) == []
            assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
            snaps = db.list_snapshots(conn)
        assert len(snaps) == 1
        assert snaps[0]["total_value"] == 10000.0
        assert sorted(app_state.market_source.get_tickers()) == sorted(db.DEFAULT_WATCHLIST)
        assert app_state.price_cache.get_price("PYPL") is None
        assert app_state.price_cache.get_price("GOOGL") == 100.0

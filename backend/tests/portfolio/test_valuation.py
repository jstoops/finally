"""Portfolio valuation and snapshots (PLAN §8)."""

from contextlib import closing

import pytest

from app import db
from app.portfolio import build_portfolio, build_watchlist, record_snapshot


@pytest.fixture
def conn(db_path):
    with closing(db.connect(db_path)) as c:
        yield c


def test_empty_portfolio(conn, price_cache):
    assert build_portfolio(conn, price_cache) == {
        "cash_balance": 10000.0,
        "positions_value": 0.0,
        "total_value": 10000.0,
        "unrealized_pnl": 0.0,
        "positions": [],
    }


def test_plan_example(conn, price_cache):
    """The GET /api/portfolio example from PLAN §8."""
    db.set_cash(conn, 8095.0)
    db.upsert_position(conn, "AAPL", 10, 190.50)
    price_cache.update("AAPL", 190.52)
    assert build_portfolio(conn, price_cache) == {
        "cash_balance": 8095.0,
        "positions_value": 1905.2,
        "total_value": 10000.2,
        "unrealized_pnl": 0.2,
        "positions": [
            {
                "ticker": "AAPL",
                "quantity": 10,
                "avg_cost": 190.5,
                "current_price": 190.52,
                "market_value": 1905.2,
                "unrealized_pnl": 0.2,
                "unrealized_pnl_percent": 0.0105,
                "weight": 1.0,
            }
        ],
    }


def test_weights_and_losses(conn, price_cache):
    db.upsert_position(conn, "AAPL", 3, 100.0)
    db.upsert_position(conn, "TSLA", 1, 200.0)
    price_cache.update("AAPL", 100.0)
    price_cache.update("TSLA", 100.0)
    p = build_portfolio(conn, price_cache)
    by = {pos["ticker"]: pos for pos in p["positions"]}
    assert by["AAPL"]["weight"] == 0.75
    assert by["TSLA"]["weight"] == 0.25
    assert by["TSLA"]["unrealized_pnl"] == -100.0
    assert by["TSLA"]["unrealized_pnl_percent"] == -50.0
    assert p["unrealized_pnl"] == -100.0
    assert p["total_value"] == 10400.0


def test_missing_price_falls_back_to_avg_cost(conn, price_cache):
    db.upsert_position(conn, "ZZZ", 2, 50.0)
    pos = build_portfolio(conn, price_cache)["positions"][0]
    assert pos["current_price"] == 50.0
    assert pos["market_value"] == 100.0
    assert pos["unrealized_pnl"] == 0.0


def test_watchlist_prices_null_until_priced(conn, price_cache):
    price_cache.update("AAPL", 190.0)
    price_cache.update("AAPL", 191.0)
    items = build_watchlist(conn, price_cache)
    assert [i["ticker"] for i in items] == db.DEFAULT_WATCHLIST
    assert items[0]["price"] == 191.0
    assert items[0]["open_price"] == 190.0
    assert items[1]["price"] is None
    assert items[1]["open_price"] is None
    assert set(items[0]) == {"ticker", "price", "open_price", "added_at"}


def test_record_snapshot(conn, price_cache):
    db.upsert_position(conn, "AAPL", 1, 100.0)
    price_cache.update("AAPL", 110.0)
    snap = record_snapshot(conn, price_cache)
    assert snap["total_value"] == 10110.0
    assert db.list_snapshots(conn)[-1]["total_value"] == 10110.0

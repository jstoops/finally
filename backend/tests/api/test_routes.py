"""REST routes: status codes and response shapes (PLAN §8)."""

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import db
from app.db import DEFAULT_WATCHLIST
from app.main import create_app

PORTFOLIO_KEYS = {"cash_balance", "positions_value", "total_value", "unrealized_pnl", "positions"}
POSITION_KEYS = {
    "ticker",
    "quantity",
    "avg_cost",
    "current_price",
    "market_value",
    "unrealized_pnl",
    "unrealized_pnl_percent",
    "weight",
}


def buy(client, ticker="AAPL", quantity=10, side="buy"):
    return client.post(
        "/api/portfolio/trade", json={"ticker": ticker, "quantity": quantity, "side": side}
    )


class TestStartup:
    def test_health(self, api_client):
        r = api_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_source_started_with_watchlist(self, api_client):
        assert api_client.source.started
        assert sorted(api_client.source.get_tickers()) == sorted(DEFAULT_WATCHLIST)

    def test_initial_snapshot(self, api_client):
        snaps = api_client.get("/api/portfolio/history").json()["snapshots"]
        assert len(snaps) == 1
        assert snaps[0]["total_value"] == 10000.0
        assert snaps[0]["recorded_at"].endswith("Z")

    def test_restart_tracks_held_positions(self, tmp_path):
        from tests.conftest import FakeSource

        sources = []

        def factory(cache):
            sources.append(FakeSource(cache))
            return sources[-1]

        def make():
            return create_app(
                db_path=str(tmp_path / "r.db"),
                static_dir=str(tmp_path / "x"),
                source_factory=factory,
            )

        with TestClient(make()) as c:
            assert buy(c, "AAPL", 1).status_code == 200
            assert c.delete("/api/watchlist/AAPL").status_code == 204
        assert sources[0].stopped
        with TestClient(make()) as c:
            assert "AAPL" in sources[1].get_tickers()
            assert c.get("/api/portfolio").json()["positions"][0]["ticker"] == "AAPL"

    def test_snapshot_task_runs(self, tmp_path):
        import time

        from tests.conftest import FakeSource

        app = create_app(
            db_path=str(tmp_path / "s.db"),
            static_dir=str(tmp_path / "x"),
            source_factory=FakeSource,
            snapshot_interval=0.05,
        )
        with TestClient(app) as c:
            deadline = time.monotonic() + 5
            while len(c.get("/api/portfolio/history").json()["snapshots"]) < 3:
                assert time.monotonic() < deadline
                time.sleep(0.05)


class TestPortfolio:
    def test_get_portfolio_shape(self, api_client):
        r = api_client.get("/api/portfolio")
        assert r.status_code == 200
        assert r.json() == {
            "cash_balance": 10000.0,
            "positions_value": 0.0,
            "total_value": 10000.0,
            "unrealized_pnl": 0.0,
            "positions": [],
        }

    def test_buy(self, api_client):
        r = buy(api_client, " aapl ", 10)
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"trade", "portfolio"}
        trade = body["trade"]
        assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
        assert trade["ticker"] == "AAPL"
        assert trade["price"] == 190.0
        portfolio = body["portfolio"]
        assert set(portfolio) == PORTFOLIO_KEYS
        assert portfolio["cash_balance"] == 8100.0
        assert set(portfolio["positions"][0]) == POSITION_KEYS
        assert portfolio["positions"][0]["weight"] == 1.0
        assert api_client.get("/api/portfolio").json() == portfolio

    def test_sell_to_zero_removes_position(self, api_client):
        buy(api_client, "AAPL", 2)
        r = buy(api_client, "AAPL", 2, "sell")
        assert r.status_code == 200
        assert r.json()["portfolio"]["positions"] == []
        assert r.json()["portfolio"]["cash_balance"] == 10000.0

    def test_trade_records_snapshot(self, api_client):
        buy(api_client, "AAPL", 1)
        assert len(api_client.get("/api/portfolio/history").json()["snapshots"]) == 2

    @pytest.mark.parametrize(
        "payload,message",
        [
            ({"ticker": "AAPL", "quantity": 1000, "side": "buy"}, "Insufficient cash"),
            ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "Insufficient shares"),
            ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "Quantity must be greater than 0"),
            ({"ticker": "AAPL", "quantity": -5, "side": "buy"}, "Quantity must be greater than 0"),
            ({"ticker": "AAPL", "quantity": 1, "side": "short"}, "Side must be"),
            ({"ticker": "123!", "quantity": 1, "side": "buy"}, "Invalid ticker"),
            ({"ticker": "ZZZZ", "quantity": 1, "side": "buy"}, "No price available for ZZZZ"),
        ],
    )
    def test_business_rule_failures_are_400(self, api_client, payload, message):
        r = api_client.post("/api/portfolio/trade", json=payload)
        assert r.status_code == 400
        assert set(r.json()) == {"error"}
        assert message in r.json()["error"]

    @pytest.mark.parametrize(
        "payload",
        [
            {"ticker": "AAPL", "side": "buy"},
            {"ticker": "AAPL", "quantity": "lots", "side": "buy"},
            {"quantity": 1, "side": "buy"},
        ],
    )
    def test_malformed_body_is_422(self, api_client, payload):
        assert api_client.post("/api/portfolio/trade", json=payload).status_code == 422


class TestWatchlist:
    def test_get_watchlist(self, api_client):
        r = api_client.get("/api/watchlist")
        assert r.status_code == 200
        tickers = r.json()["tickers"]
        assert [t["ticker"] for t in tickers] == DEFAULT_WATCHLIST
        assert tickers[0] == {
            "ticker": "AAPL",
            "price": 190.0,
            "open_price": 190.0,
            "added_at": tickers[0]["added_at"],
        }

    def test_add_new_is_201(self, api_client):
        r = api_client.post("/api/watchlist", json={"ticker": " pypl "})
        assert r.status_code == 201
        body = r.json()
        assert body["ticker"] == "PYPL"
        assert body["price"] == 100.0
        assert set(body) == {"ticker", "price", "open_price", "added_at"}
        assert api_client.get("/api/watchlist").json()["tickers"][-1]["ticker"] == "PYPL"
        assert "PYPL" in api_client.source.get_tickers()

    def test_add_existing_is_200(self, api_client):
        r = api_client.post("/api/watchlist", json={"ticker": "aapl"})
        assert r.status_code == 200
        assert r.json()["ticker"] == "AAPL"
        assert len(api_client.get("/api/watchlist").json()["tickers"]) == 10

    def test_add_malformed_is_400(self, api_client):
        r = api_client.post("/api/watchlist", json={"ticker": "not a ticker"})
        assert r.status_code == 400
        assert "Invalid ticker" in r.json()["error"]

    def test_add_missing_field_is_422(self, api_client):
        assert api_client.post("/api/watchlist", json={}).status_code == 422

    def test_delete_is_204(self, api_client):
        r = api_client.delete("/api/watchlist/googl")
        assert r.status_code == 204
        assert r.content == b""
        tickers = [t["ticker"] for t in api_client.get("/api/watchlist").json()["tickers"]]
        assert "GOOGL" not in tickers
        assert "GOOGL" not in api_client.source.get_tickers()

    def test_delete_missing_is_404(self, api_client):
        r = api_client.delete("/api/watchlist/PYPL")
        assert r.status_code == 404
        assert r.json() == {"error": "PYPL is not on the watchlist"}

    def test_delete_malformed_is_400(self, api_client):
        r = api_client.delete("/api/watchlist/bad$")
        assert r.status_code == 400
        assert "Invalid ticker" in r.json()["error"]

    def test_delete_held_keeps_pricing(self, api_client):
        buy(api_client, "AAPL", 1)
        assert api_client.delete("/api/watchlist/AAPL").status_code == 204
        assert "AAPL" in api_client.source.get_tickers()
        pos = api_client.get("/api/portfolio").json()["positions"][0]
        assert pos["current_price"] == 190.0

    def test_unwatched_ticker_sold_to_zero_is_dropped(self, api_client):
        buy(api_client, "AAPL", 1)
        api_client.delete("/api/watchlist/AAPL")
        buy(api_client, "AAPL", 1, "sell")
        assert "AAPL" not in api_client.source.get_tickers()


class TestReset:
    def test_reset(self, api_client):
        api_client.post("/api/watchlist", json={"ticker": "PYPL"})
        api_client.delete("/api/watchlist/GOOGL")
        buy(api_client, "NVDA", 5)
        with closing(api_client.app.state.ctx.connect()) as conn:
            db.insert_chat_message(conn, "user", "hello")

        r = api_client.post("/api/reset")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

        portfolio = api_client.get("/api/portfolio").json()
        assert portfolio["cash_balance"] == 10000.0
        assert portfolio["positions"] == []
        tickers = [t["ticker"] for t in api_client.get("/api/watchlist").json()["tickers"]]
        assert tickers == DEFAULT_WATCHLIST
        assert sorted(api_client.source.get_tickers()) == sorted(DEFAULT_WATCHLIST)
        snaps = api_client.get("/api/portfolio/history").json()["snapshots"]
        assert [s["total_value"] for s in snaps] == [10000.0]
        assert api_client.get("/api/chat/history").json()["messages"] == []


class TestMarketRoutes:
    def test_price_history(self, api_client):
        r = api_client.get("/api/prices/aapl/history")
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["points"][0]["price"] == 190.0

    def test_untracked_history_is_empty(self, api_client):
        assert api_client.get("/api/prices/QQQ/history").json() == {"ticker": "QQQ", "points": []}


class TestErrorsAndStatic:
    def test_unknown_api_route_is_json_404(self, api_client):
        r = api_client.get("/api/nope")
        assert r.status_code == 404
        assert r.json() == {"error": "Not Found"}

    def test_static_files_served_after_api(self, tmp_path):
        from tests.conftest import FakeSource

        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<h1>FinAlly</h1>")
        app = create_app(
            db_path=str(tmp_path / "st.db"), static_dir=str(static), source_factory=FakeSource
        )
        with TestClient(app) as c:
            assert c.get("/").text == "<h1>FinAlly</h1>"
            assert c.get("/api/health").json() == {"status": "ok"}

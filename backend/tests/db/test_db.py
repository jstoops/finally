"""Tests for the SQLite persistence layer (app.db)."""

import re
import sqlite3

import pytest

from app import db

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "nested" / "finally.db")
    db.init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    c = db.connect(db_path)
    yield c
    c.close()


def tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestInit:
    def test_creates_parent_dir_and_all_tables(self, conn):
        assert tables(conn) >= {
            "users_profile",
            "watchlist",
            "positions",
            "trades",
            "portfolio_snapshots",
            "chat_messages",
        }

    def test_seed_contents(self, conn):
        assert db.get_cash(conn) == 10000.0
        assert [w["ticker"] for w in db.list_watchlist(conn)] == db.DEFAULT_WATCHLIST
        assert db.list_positions(conn) == []
        assert db.list_snapshots(conn) == []
        assert db.list_chat_messages(conn) == []

    def test_seed_rows_have_uuid_ids_and_iso_timestamps(self, conn):
        rows = conn.execute("SELECT id, user_id, added_at FROM watchlist").fetchall()
        assert all(UUID.match(r["id"]) for r in rows)
        assert all(r["user_id"] == "default" for r in rows)
        assert all(ISO_Z.match(r["added_at"]) for r in rows)
        profile = conn.execute("SELECT * FROM users_profile").fetchone()
        assert profile["id"] == "default"
        assert ISO_Z.match(profile["created_at"])

    def test_idempotent(self, db_path, conn):
        db.init_db(db_path)
        db.init_db(db_path)
        assert count(conn, "users_profile") == 1
        assert count(conn, "watchlist") == len(db.DEFAULT_WATCHLIST)

    def test_reinit_preserves_user_data(self, db_path, conn):
        db.set_cash(conn, 1234.5)
        db.add_watchlist(conn, "PYPL")
        db.remove_watchlist(conn, "AAPL")
        db.upsert_position(conn, "MSFT", 2, 400.0)
        db.init_db(db_path)
        assert db.get_cash(conn) == 1234.5
        tickers = [w["ticker"] for w in db.list_watchlist(conn)]
        assert "PYPL" in tickers
        assert "AAPL" not in tickers  # removed default is not re-seeded
        assert db.get_position(conn, "MSFT")["quantity"] == 2

    def test_default_columns(self, conn):
        conn.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, executed_at) "
            "VALUES ('t1', 'AAPL', 'buy', 1, 1, 'x')"
        )
        assert conn.execute("SELECT user_id FROM trades").fetchone()[0] == "default"

    def test_check_constraints(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_trade(conn, "AAPL", "hold", 1, 1)
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_chat_message(conn, "system", "hi")

    def test_connect_settings(self, conn):
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_now_iso_format():
    assert ISO_Z.match(db.now_iso())


class TestTransaction:
    def test_commit(self, db_path, conn):
        with db.transaction(conn):
            db.set_cash(conn, 5.0)
            db.upsert_position(conn, "AAPL", 1, 1.0)
        other = db.connect(db_path)
        assert db.get_cash(other) == 5.0
        assert db.get_position(other, "AAPL") is not None
        other.close()

    def test_rollback_on_error(self, conn):
        with pytest.raises(RuntimeError):
            with db.transaction(conn):
                db.set_cash(conn, 5.0)
                db.insert_trade(conn, "AAPL", "buy", 1, 1)
                raise RuntimeError("boom")
        assert db.get_cash(conn) == 10000.0
        assert count(conn, "trades") == 0
        assert not conn.in_transaction

    def test_rollback_on_integrity_error(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction(conn):
                db.set_cash(conn, 1.0)
                db.insert_trade(conn, "AAPL", "bogus", 1, 1)
        assert db.get_cash(conn) == 10000.0

    def test_usable_after_rollback(self, conn):
        with pytest.raises(ValueError):
            with db.transaction(conn):
                raise ValueError
        with db.transaction(conn):
            db.set_cash(conn, 7.0)
        assert db.get_cash(conn) == 7.0


class TestCash:
    def test_set_and_get(self, conn):
        db.set_cash(conn, 8095.25)
        assert db.get_cash(conn) == 8095.25

    def test_other_user(self, conn):
        db.set_cash(conn, 1.0, user_id="bob")
        assert db.get_cash(conn, user_id="bob") == 1.0
        assert db.get_cash(conn) == 10000.0

    def test_missing_user_raises(self, conn):
        with pytest.raises(LookupError):
            db.get_cash(conn, user_id="nobody")


class TestWatchlist:
    def test_add_new(self, conn):
        entry, created = db.add_watchlist(conn, "PYPL")
        assert created is True
        assert entry["ticker"] == "PYPL"
        assert ISO_Z.match(entry["added_at"])
        assert set(entry) == {"ticker", "added_at"}
        assert db.list_watchlist(conn)[-1]["ticker"] == "PYPL"

    def test_add_existing_is_idempotent(self, conn):
        before = db.get_watchlist_entry(conn, "AAPL")
        entry, created = db.add_watchlist(conn, "AAPL")
        assert created is False
        assert entry == before
        assert count(conn, "watchlist") == len(db.DEFAULT_WATCHLIST)

    def test_normalizes_ticker(self, conn):
        entry, created = db.add_watchlist(conn, "  pypl ")
        assert created and entry["ticker"] == "PYPL"
        assert db.get_watchlist_entry(conn, "pypl")["ticker"] == "PYPL"

    def test_get_missing(self, conn):
        assert db.get_watchlist_entry(conn, "ZZZZ") is None

    def test_remove(self, conn):
        assert db.remove_watchlist(conn, "TSLA") is True
        assert db.get_watchlist_entry(conn, "TSLA") is None
        assert db.remove_watchlist(conn, "TSLA") is False

    def test_order_ties_broken_by_insertion(self, conn):
        for t in ["ZZZ", "AAA", "MMM"]:
            db.add_watchlist(conn, t)
        assert [w["ticker"] for w in db.list_watchlist(conn)][-3:] == ["ZZZ", "AAA", "MMM"]

    def test_per_user(self, conn):
        db.add_watchlist(conn, "PYPL", user_id="bob")
        assert [w["ticker"] for w in db.list_watchlist(conn, user_id="bob")] == ["PYPL"]
        assert db.get_watchlist_entry(conn, "PYPL") is None


class TestPositions:
    def test_insert_and_get(self, conn):
        db.upsert_position(conn, "AAPL", 10, 190.5)
        pos = db.get_position(conn, "AAPL")
        assert pos["ticker"] == "AAPL"
        assert pos["quantity"] == 10
        assert pos["avg_cost"] == 190.5
        assert ISO_Z.match(pos["updated_at"])
        assert set(pos) == {"ticker", "quantity", "avg_cost", "updated_at"}

    def test_update_keeps_single_row(self, conn):
        db.upsert_position(conn, "AAPL", 10, 190.5)
        db.upsert_position(conn, "AAPL", 15.1234, 191.0)
        assert count(conn, "positions") == 1
        pos = db.get_position(conn, "AAPL")
        assert pos["quantity"] == 15.1234
        assert pos["avg_cost"] == 191.0

    def test_list_ticker_order(self, conn):
        for t in ["TSLA", "AAPL", "MSFT"]:
            db.upsert_position(conn, t, 1, 1.0)
        assert [p["ticker"] for p in db.list_positions(conn)] == ["AAPL", "MSFT", "TSLA"]

    def test_delete(self, conn):
        db.upsert_position(conn, "AAPL", 1, 1.0)
        db.delete_position(conn, "AAPL")
        assert db.get_position(conn, "AAPL") is None
        db.delete_position(conn, "AAPL")  # no error when absent

    def test_get_missing(self, conn):
        assert db.get_position(conn, "AAPL") is None


class TestTrades:
    def test_insert_returns_dict(self, conn):
        trade = db.insert_trade(conn, "AAPL", "buy", 10, 190.5)
        assert UUID.match(trade["id"])
        assert ISO_Z.match(trade["executed_at"])
        assert {k: trade[k] for k in ("ticker", "side", "quantity", "price")} == {
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 10.0,
            "price": 190.5,
        }
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade["id"],)).fetchone()
        assert row["user_id"] == "default"
        assert row["price"] == 190.5

    def test_append_only(self, conn):
        db.insert_trade(conn, "AAPL", "buy", 1, 1)
        db.insert_trade(conn, "AAPL", "sell", 1, 2)
        assert count(conn, "trades") == 2


class TestSnapshots:
    def test_insert_and_list_oldest_first(self, conn):
        s1 = db.insert_snapshot(conn, 10000.0)
        db.insert_snapshot(conn, 10050.5)
        db.insert_snapshot(conn, 9990.0)
        assert set(s1) == {"total_value", "recorded_at"}
        assert ISO_Z.match(s1["recorded_at"])
        assert [s["total_value"] for s in db.list_snapshots(conn)] == [10000.0, 10050.5, 9990.0]

    def test_per_user(self, conn):
        db.insert_snapshot(conn, 1.0, user_id="bob")
        assert db.list_snapshots(conn) == []


class TestChat:
    def test_user_message_null_actions(self, conn):
        msg = db.insert_chat_message(conn, "user", "Buy 5 NVDA")
        assert msg["actions"] is None
        assert set(msg) == {"id", "role", "content", "actions", "created_at"}
        assert UUID.match(msg["id"])
        raw = conn.execute("SELECT actions FROM chat_messages").fetchone()[0]
        assert raw is None
        assert db.list_chat_messages(conn) == [msg]

    def test_actions_json_round_trip(self, conn):
        actions = {
            "trades": [
                {
                    "ticker": "NVDA",
                    "side": "buy",
                    "quantity": 5,
                    "status": "executed",
                    "price": 875.2,
                }
            ],
            "watchlist_changes": [
                {"ticker": "PYPL", "action": "add", "status": "failed", "error": "nope ⚠️"}
            ],
        }
        msg = db.insert_chat_message(conn, "assistant", "Done.", actions)
        assert msg["actions"] == actions
        [stored] = db.list_chat_messages(conn)
        assert stored["actions"] == actions
        assert stored["id"] == msg["id"]

    def test_limit_returns_latest_oldest_first(self, conn):
        for i in range(60):
            db.insert_chat_message(conn, "user" if i % 2 == 0 else "assistant", f"m{i}")
        msgs = db.list_chat_messages(conn)
        assert len(msgs) == 50
        assert [m["content"] for m in msgs] == [f"m{i}" for i in range(10, 60)]
        last20 = db.list_chat_messages(conn, limit=20)
        assert [m["content"] for m in last20] == [f"m{i}" for i in range(40, 60)]

    def test_limit_larger_than_count(self, conn):
        db.insert_chat_message(conn, "user", "a")
        db.insert_chat_message(conn, "assistant", "b")
        assert [m["content"] for m in db.list_chat_messages(conn, limit=100)] == ["a", "b"]

    def test_limit_zero(self, conn):
        db.insert_chat_message(conn, "user", "a")
        assert db.list_chat_messages(conn, limit=0) == []


class TestReset:
    def test_reset_restores_seeded_state(self, conn):
        db.set_cash(conn, 1.0)
        db.upsert_position(conn, "AAPL", 3, 100.0)
        db.insert_trade(conn, "AAPL", "buy", 3, 100.0)
        db.insert_snapshot(conn, 10000.0)
        db.insert_chat_message(conn, "user", "hi")
        db.add_watchlist(conn, "PYPL")
        db.remove_watchlist(conn, "AAPL")
        db.remove_watchlist(conn, "NFLX")

        with db.transaction(conn):
            db.reset_user(conn)

        assert db.get_cash(conn) == 10000.0
        assert db.list_positions(conn) == []
        assert count(conn, "trades") == 0
        assert db.list_snapshots(conn) == []
        assert db.list_chat_messages(conn) == []
        assert [w["ticker"] for w in db.list_watchlist(conn)] == db.DEFAULT_WATCHLIST

    def test_reset_only_affects_user(self, conn):
        db.set_cash(conn, 1.0, user_id="bob")
        db.insert_trade(conn, "AAPL", "buy", 1, 1, user_id="bob")
        db.reset_user(conn)
        assert db.get_cash(conn, user_id="bob") == 1.0
        assert count(conn, "trades") == 1

    def test_reset_rolls_back_with_transaction(self, conn):
        db.insert_trade(conn, "AAPL", "buy", 1, 1)
        with pytest.raises(RuntimeError):
            with db.transaction(conn):
                db.reset_user(conn)
                raise RuntimeError
        assert count(conn, "trades") == 1

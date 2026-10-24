"""handle_chat orchestration (PLAN §9 steps 1-10) against a real temp DB and portfolio."""

from contextlib import closing

import pytest

from app import db, portfolio
from app.llm import ChatResponse, LLMCallFailed, LLMNotConfigured, handle_chat
from app.llm import chat as chat_module
from app.llm.mock import GREETING


def _messages(state):
    with closing(db.connect(state.db_path)) as conn:
        return db.list_chat_messages(conn, limit=100)


def _cash(state):
    with closing(db.connect(state.db_path)) as conn:
        return db.get_cash(conn)


def _position(state, ticker):
    with closing(db.connect(state.db_path)) as conn:
        return db.get_position(conn, ticker)


def _watchlist(state):
    with closing(db.connect(state.db_path)) as conn:
        return [e["ticker"] for e in db.list_watchlist(conn)]


def stub_llm(monkeypatch, response: ChatResponse | Exception):
    """Replace the network call; records the messages it was given."""
    calls = []

    async def fake_call_llm(messages):
        calls.append(messages)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(chat_module, "call_llm", fake_call_llm)
    return calls


# --- Mock mode ---


async def test_mock_greeting_stores_both_messages(state, mock_mode):
    result = await handle_chat(state, "hello there")
    assert result["role"] == "assistant"
    assert result["content"] == GREETING
    assert result["actions"] is None
    assert set(result) >= {"id", "role", "content", "actions", "created_at"}
    stored = _messages(state)
    assert [(m["role"], m["content"]) for m in stored] == [
        ("user", "hello there"),
        ("assistant", GREETING),
    ]
    assert stored[1]["id"] == result["id"]


async def test_mock_buy_executes_trade(state, mock_mode):
    result = await handle_chat(state, "Buy something")
    assert result["content"] == "Buying 1 share of AAPL."
    assert result["actions"] == {
        "trades": [
            {"ticker": "AAPL", "side": "buy", "quantity": 1, "status": "executed", "price": 190.0}
        ],
        "watchlist_changes": [],
    }
    assert _cash(state) == pytest.approx(10000 - 190.0)
    assert _position(state, "AAPL")["quantity"] == pytest.approx(1)


async def test_mock_sell_without_position_fails_with_note(state, mock_mode):
    result = await handle_chat(state, "sell")
    trade = result["actions"]["trades"][0]
    assert trade["status"] == "failed"
    assert trade["error"]
    assert "price" not in trade
    assert result["content"].startswith("Selling 1 share of AAPL.\n\n⚠️ Couldn't sell 1 AAPL: ")
    assert _cash(state) == pytest.approx(10000)


async def test_mock_add_and_remove_watchlist(state, mock_mode):
    result = await handle_chat(state, "add pypl")
    assert result["actions"]["watchlist_changes"] == [
        {"ticker": "PYPL", "action": "add", "status": "executed"}
    ]
    assert "PYPL" in _watchlist(state)
    assert state.price_cache.get_price("PYPL") is not None

    result = await handle_chat(state, "remove PYPL")
    assert result["actions"]["watchlist_changes"][0]["status"] == "executed"
    assert "PYPL" not in _watchlist(state)


async def test_mock_remove_missing_ticker_fails(state, mock_mode):
    result = await handle_chat(state, "remove ZZZZ")
    change = result["actions"]["watchlist_changes"][0]
    assert change["status"] == "failed"
    assert change["error"]
    assert "⚠️ Couldn't remove ZZZZ from your watchlist: " in result["content"]


# --- Configuration ---


async def test_not_configured_raises_before_storing(state, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMNotConfigured) as exc:
        await handle_chat(state, "hi")
    assert str(exc.value) == "AI assistant is not configured. Set OPENROUTER_API_KEY in .env."
    assert _messages(state) == []


async def test_mock_mode_needs_no_key(state, mock_mode):
    assert (await handle_chat(state, "hi"))["content"] == GREETING


# --- Real path with stubbed LLM ---


async def test_llm_failure_keeps_user_message(state, real_mode, monkeypatch):
    stub_llm(monkeypatch, LLMCallFailed("bad output"))
    with pytest.raises(LLMCallFailed):
        await handle_chat(state, "analyze me")
    assert [(m["role"], m["content"]) for m in _messages(state)] == [("user", "analyze me")]


async def test_prompt_contains_context_and_history(state, real_mode, monkeypatch):
    calls = stub_llm(monkeypatch, ChatResponse(message="first"))
    await handle_chat(state, "one")
    await handle_chat(state, "two")
    msgs = calls[1]
    assert "FinAlly, an AI trading assistant" in msgs[0]["content"]
    assert "Cash: $10,000.00" in msgs[1]["content"]
    assert "AAPL: $190.00" in msgs[1]["content"]
    assert msgs[2:] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "two"},
    ]


async def test_history_limited_to_20(state, real_mode, monkeypatch):
    with closing(db.connect(state.db_path)) as conn:
        for i in range(30):
            db.insert_chat_message(conn, "user" if i % 2 == 0 else "assistant", f"m{i}")
        conn.commit()
    calls = stub_llm(monkeypatch, ChatResponse(message="ok"))
    await handle_chat(state, "new")
    history = calls[0][2:-1]
    assert len(history) == 20
    assert history[0]["content"] == "m10" and history[-1]["content"] == "m29"
    assert calls[0][-1] == {"role": "user", "content": "new"}


async def test_watchlist_runs_before_trades(state, real_mode, monkeypatch):
    stub_llm(
        monkeypatch,
        ChatResponse.model_validate(
            {
                "message": "Adding and buying PYPL.",
                "trades": [{"ticker": "pypl", "side": "buy", "quantity": 2}],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
            }
        ),
    )
    result = await handle_chat(state, "get me pypl")
    assert result["actions"]["watchlist_changes"][0]["status"] == "executed"
    trade = result["actions"]["trades"][0]
    assert trade["status"] == "executed"
    assert trade["ticker"] == "PYPL"
    assert trade["price"] == state.price_cache.get_price("PYPL")
    assert result["content"] == "Adding and buying PYPL."


async def test_partial_failures_execute_independently(state, real_mode, monkeypatch):
    stub_llm(
        monkeypatch,
        ChatResponse.model_validate(
            {
                "message": "On it.",
                "trades": [
                    {"ticker": "TSLA", "side": "buy", "quantity": 1000},  # insufficient cash
                    {"ticker": "AAPL", "side": "buy", "quantity": 2},
                    {"ticker": "NVDA", "side": "sell", "quantity": 1},  # nothing held
                    {"ticker": "bad ticker!", "side": "buy", "quantity": 1},  # malformed
                    {"ticker": "GOOGL", "side": "buy", "quantity": 0},  # bad quantity
                ],
                "watchlist_changes": [
                    {"ticker": "!!!", "action": "add"},
                    {"ticker": "AMD", "action": "add"},
                ],
            }
        ),
    )
    result = await handle_chat(state, "do stuff")
    trades = result["actions"]["trades"]
    assert [t["status"] for t in trades] == ["failed", "executed", "failed", "failed", "failed"]
    assert all(t["error"] for t in trades if t["status"] == "failed")
    assert [c["status"] for c in result["actions"]["watchlist_changes"]] == ["failed", "executed"]
    assert _position(state, "AAPL")["quantity"] == pytest.approx(2)
    assert _cash(state) == pytest.approx(10000 - 2 * 190.0)
    assert "AMD" in _watchlist(state)

    lines = result["content"].split("\n")
    assert lines[0] == "On it."
    notes = [ln for ln in lines if ln.startswith("⚠️")]
    assert len(notes) == 5
    # watchlist notes come first, matching execution order
    assert notes[0].startswith("⚠️ Couldn't add !!! to your watchlist: ")
    assert notes[1].startswith("⚠️ Couldn't buy 1,000 TSLA: ")
    assert notes[2].startswith("⚠️ Couldn't sell 1 NVDA: ")
    assert _messages(state)[-1]["content"] == result["content"]


async def test_no_price_failure(state, real_mode, monkeypatch):
    state.price_cache.remove("AAPL")
    stub_llm(
        monkeypatch,
        ChatResponse.model_validate(
            {"message": "Buying.", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}]}
        ),
    )
    result = await handle_chat(state, "buy")
    assert result["actions"]["trades"][0]["status"] == "failed"
    assert "AAPL" in result["actions"]["trades"][0]["error"]


async def test_unexpected_exception_is_contained(state, real_mode, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(portfolio, "execute_trade", explode)
    stub_llm(
        monkeypatch,
        ChatResponse.model_validate(
            {"message": "Buying.", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}]}
        ),
    )
    result = await handle_chat(state, "buy")
    trade = result["actions"]["trades"][0]
    assert trade["status"] == "failed"
    assert "secret" not in trade["error"]


def test_compose_message_lowercases_sentence_errors():
    actions = {
        "watchlist_changes": [],
        "trades": [
            {
                "ticker": "TSLA",
                "side": "buy",
                "quantity": 50,
                "status": "failed",
                "error": "Insufficient cash (need $12,450.00, have $8,095.00)",
            },
            {
                "ticker": "XYZ",
                "side": "sell",
                "quantity": 0.25,
                "status": "failed",
                "error": "XYZ is not held",
            },
        ],
    }
    assert chat_module.compose_message("Ok.", actions) == (
        "Ok.\n\n"
        "⚠️ Couldn't buy 50 TSLA: insufficient cash (need $12,450.00, have $8,095.00)\n"
        "⚠️ Couldn't sell 0.25 XYZ: XYZ is not held"
    )
    assert chat_module.compose_message("Ok.", None) == "Ok."

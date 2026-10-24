"""Structured output parsing and the LiteLLM call (no network)."""

import json
from types import SimpleNamespace

import pytest

from app.llm import client
from app.llm.client import LLMCallFailed, call_llm, parse_response


def test_parse_message_only():
    r = parse_response('{"message": "hi"}')
    assert r.message == "hi" and r.trades == [] and r.watchlist_changes == []


def test_parse_empty_action_lists():
    r = parse_response('{"message": "hi", "trades": [], "watchlist_changes": []}')
    assert r.trades == [] and r.watchlist_changes == []


def test_parse_full_schema():
    payload = {
        "message": "Done.",
        "trades": [
            {"ticker": "AAPL", "side": "buy", "quantity": 10},
            {"ticker": "TSLA", "side": "sell", "quantity": 0.5},
        ],
        "watchlist_changes": [
            {"ticker": "PYPL", "action": "add"},
            {"ticker": "NFLX", "action": "remove"},
        ],
    }
    r = parse_response(json.dumps(payload))
    assert r.model_dump() == payload


def test_parse_trades_only_and_watchlist_only():
    trade = '{"message": "", "trades": [{"ticker": "V", "side": "buy", "quantity": 1}]}'
    assert len(parse_response(trade).trades) == 1
    r = parse_response('{"message": "x", "watchlist_changes": [{"ticker": "V", "action": "add"}]}')
    assert r.watchlist_changes[0].action == "add"


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "   ",
        "not json",
        '{"message": "unterminated',
        "[]",
        '{"trades": []}',  # missing message
        '{"message": "x", "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1}]}',
        '{"message": "x", "trades": [{"ticker": "AAPL", "side": "buy"}]}',
        '{"message": "x", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": "lots"}]}',
        '{"message": "x", "watchlist_changes": [{"ticker": "AAPL", "action": "watch"}]}',
        '{"message": "x", "trades": {"ticker": "AAPL"}}',
    ],
)
def test_parse_malformed_raises(content):
    with pytest.raises(LLMCallFailed):
        parse_response(content)


def _fake_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def test_call_llm_passes_cerebras_settings(monkeypatch):
    seen = {}

    async def fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _fake_response('{"message": "ok"}')

    monkeypatch.setattr(client.litellm, "acompletion", fake_acompletion)
    msgs = [{"role": "user", "content": "hi"}]
    r = await call_llm(msgs)
    assert r.message == "ok"
    assert seen["model"] == "openrouter/openai/gpt-oss-120b"
    assert seen["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert seen["response_format"] is client.ChatResponse
    assert seen["messages"] == msgs


async def test_call_llm_wraps_exceptions(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(client.litellm, "acompletion", boom)
    with pytest.raises(LLMCallFailed):
        await call_llm([])


async def test_call_llm_unparseable(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _fake_response("Sure! I bought it.")

    monkeypatch.setattr(client.litellm, "acompletion", fake_acompletion)
    with pytest.raises(LLMCallFailed):
        await call_llm([])


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("false", False), ("", False), ("1", False)],
)
def test_is_mock_mode(monkeypatch, value, expected):
    monkeypatch.setenv("LLM_MOCK", value)
    assert client.is_mock_mode() is expected


def test_is_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  ")
    assert not client.is_configured()
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert client.is_configured()

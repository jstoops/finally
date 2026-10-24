"""LLM_MOCK deterministic responses (PLAN §9 table)."""

import pytest

from app.llm.mock import GREETING, mock_response


@pytest.mark.parametrize(
    "text", ["buy", "Please BUY something", "buy and sell", "add TSLA and buy"]
)
def test_buy_rule_wins_first(text):
    r = mock_response(text)
    assert r.message == "Buying 1 share of AAPL."
    assert [t.model_dump() for t in r.trades] == [{"ticker": "AAPL", "side": "buy", "quantity": 1}]
    assert r.watchlist_changes == []


@pytest.mark.parametrize("text", ["sell", "Sell it all", "remove AAPL then sell"])
def test_sell_rule(text):
    r = mock_response(text)
    assert r.message == "Selling 1 share of AAPL."
    assert [t.model_dump() for t in r.trades] == [{"ticker": "AAPL", "side": "sell", "quantity": 1}]


@pytest.mark.parametrize(
    ("text", "ticker"),
    [("add PYPL", "PYPL"), ("Please ADD pypl to my list", "PYPL"), ("add brk.b.", "BRK.B")],
)
def test_add_rule_extracts_ticker(text, ticker):
    r = mock_response(text)
    assert r.message == f"Adding {ticker} to your watchlist."
    assert [c.model_dump() for c in r.watchlist_changes] == [{"ticker": ticker, "action": "add"}]
    assert r.trades == []


def test_remove_rule_extracts_ticker():
    r = mock_response("Remove netflix")
    assert r.message == "Removing NETFLIX from your watchlist."
    assert [c.model_dump() for c in r.watchlist_changes] == [
        {"ticker": "NETFLIX", "action": "remove"}
    ]


def test_add_beats_remove():
    r = mock_response("add AMD, remove NFLX")
    assert r.watchlist_changes[0].ticker == "AMD"


@pytest.mark.parametrize("text", ["hello", "what is my address?", "add", "removed it", ""])
def test_fallback_greeting(text):
    r = mock_response(text)
    assert r.message == GREETING
    assert r.trades == [] and r.watchlist_changes == []

"""Prompt construction: system prompt, portfolio context, history."""

from app.llm.prompt import SYSTEM_PROMPT, build_context, build_messages

PORTFOLIO = {
    "cash_balance": 8095.0,
    "positions_value": 1905.2,
    "total_value": 10000.2,
    "unrealized_pnl": -12.5,
    "positions": [
        {
            "ticker": "AAPL",
            "quantity": 10.5,
            "avg_cost": 190.5,
            "current_price": 190.52,
            "market_value": 1905.2,
            "unrealized_pnl": 0.2,
            "unrealized_pnl_percent": 0.0105,
            "weight": 1.0,
        }
    ],
}


def test_system_prompt_identity():
    assert "FinAlly, an AI trading assistant" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT


def test_context_includes_portfolio_and_watchlist():
    ctx = build_context(
        PORTFOLIO,
        [
            {"ticker": "AAPL", "price": 190.52, "open_price": 190.0},
            {"ticker": "PYPL", "price": None, "open_price": None},
        ],
    )
    assert "Cash: $8,095.00" in ctx
    assert "Total portfolio value: $10,000.20" in ctx
    assert "Unrealized P&L: -$12.50" in ctx
    assert "AAPL: 10.5 shares, avg cost $190.50" in ctx
    assert "weight 100.0%" in ctx
    assert "AAPL: $190.52 (Chg +0.27%)" in ctx
    assert "PYPL: no price yet" in ctx


def test_context_empty_portfolio():
    ctx = build_context({**PORTFOLIO, "positions": []}, [])
    assert "Positions:\n- (none)" in ctx
    assert "- (empty)" in ctx


def test_build_messages_order():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    msgs = build_messages("CTX", history, "buy 1 AAPL")
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert msgs[1] == {"role": "system", "content": "CTX"}
    assert msgs[2:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "buy 1 AAPL"},
    ]

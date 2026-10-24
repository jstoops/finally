"""System prompt, portfolio context and conversation history for the LLM call."""

from __future__ import annotations

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading workstation.
The user trades a virtual portfolio with fake money; market orders fill instantly at the current price.

Your job:
- Analyze portfolio composition, risk concentration and P&L.
- Suggest trades with brief reasoning.
- Execute trades when the user asks for them or agrees to your suggestion, by listing them in "trades".
- Manage the watchlist proactively via "watchlist_changes" (e.g. add a ticker the user asks about).
- Be concise and data-driven: cite prices, weights and P&L from the portfolio context.

Rules:
- Always respond with valid JSON matching the schema: {"message": str, "trades": [{"ticker", "side": "buy"|"sell", "quantity"}], "watchlist_changes": [{"ticker", "action": "add"|"remove"}]}.
- Use empty lists when no action is needed. Only include actions the user requested or agreed to.
- Tickers are uppercase symbols. Quantities are share counts (fractions allowed) and must be positive.
- Buys need enough cash; sells cannot exceed the shares held. Check the context before proposing.
- Actions execute right after you reply, so describe them in "message" as being done (e.g. "Buying 5 NVDA.").
"""


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _signed_money(value: float) -> str:
    return ("+" if value >= 0 else "") + _money(value)


def _qty(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def build_context(portfolio: dict, watchlist: list[dict]) -> str:
    """Render the portfolio (build_portfolio shape) and priced watchlist as prompt text.

    `watchlist` items: {"ticker", "price", "open_price"} with prices possibly None.
    """
    lines = [
        "Current portfolio state:",
        f"- Cash: {_money(portfolio['cash_balance'])}",
        f"- Positions value: {_money(portfolio['positions_value'])}",
        f"- Total portfolio value: {_money(portfolio['total_value'])}",
        f"- Unrealized P&L: {_signed_money(portfolio['unrealized_pnl'])}",
        "",
        "Positions:",
    ]
    positions = portfolio.get("positions") or []
    if not positions:
        lines.append("- (none)")
    for p in positions:
        lines.append(
            f"- {p['ticker']}: {_qty(p['quantity'])} shares, avg cost {_money(p['avg_cost'])}, "
            f"price {_money(p['current_price'])}, value {_money(p['market_value'])}, "
            f"P&L {_signed_money(p['unrealized_pnl'])} ({p['unrealized_pnl_percent']:+.2f}%), "
            f"weight {p['weight'] * 100:.1f}%"
        )

    lines += ["", "Watchlist (Chg % is since session open):"]
    if not watchlist:
        lines.append("- (empty)")
    for w in watchlist:
        price, open_price = w.get("price"), w.get("open_price")
        if price is None:
            lines.append(f"- {w['ticker']}: no price yet")
        elif open_price:
            chg = (price - open_price) / open_price * 100
            lines.append(f"- {w['ticker']}: {_money(price)} (Chg {chg:+.2f}%)")
        else:
            lines.append(f"- {w['ticker']}: {_money(price)}")
    return "\n".join(lines)


def build_messages(context: str, history: list[dict], user_message: str) -> list[dict]:
    """System prompt + portfolio context + prior turns (oldest first) + the new user message."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ]
    messages += [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m["role"] in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": user_message})
    return messages

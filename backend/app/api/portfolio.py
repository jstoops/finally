"""Portfolio routes: valuation, trades, history, reset (PLAN §8)."""

from __future__ import annotations

from contextlib import closing

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.portfolio import PortfolioError, build_portfolio, execute_trade, reset_account

router = APIRouter(tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str


@router.get("/api/portfolio")
def get_portfolio(request: Request) -> dict:
    ctx = request.app.state.ctx
    with closing(ctx.connect()) as conn:
        return build_portfolio(conn, ctx.price_cache)


@router.post("/api/portfolio/trade")
async def post_trade(body: TradeRequest, request: Request) -> dict:
    ctx = request.app.state.ctx
    try:
        trade = await execute_trade(ctx, body.ticker, body.side, body.quantity)
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with closing(ctx.connect()) as conn:
        return {"trade": trade, "portfolio": build_portfolio(conn, ctx.price_cache)}


@router.get("/api/portfolio/history")
def get_portfolio_history(request: Request) -> dict:
    with closing(request.app.state.ctx.connect()) as conn:
        return {"snapshots": db.list_snapshots(conn)}


@router.post("/api/reset")
async def post_reset(request: Request) -> dict:
    await reset_account(request.app.state.ctx)
    return {"status": "ok"}

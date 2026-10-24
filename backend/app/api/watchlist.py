"""Watchlist routes (PLAN §8)."""

from __future__ import annotations

from contextlib import closing

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.portfolio import (
    PortfolioError,
    add_to_watchlist,
    build_watchlist,
    remove_from_watchlist,
    watchlist_item,
)

router = APIRouter(tags=["watchlist"])


class WatchlistRequest(BaseModel):
    ticker: str


@router.get("/api/watchlist")
def get_watchlist(request: Request) -> dict:
    ctx = request.app.state.ctx
    with closing(ctx.connect()) as conn:
        return {"tickers": build_watchlist(conn, ctx.price_cache)}


@router.post("/api/watchlist", status_code=201)
async def post_watchlist(body: WatchlistRequest, request: Request) -> JSONResponse:
    """201 with the new entry, or 200 with the existing one (idempotent)."""
    ctx = request.app.state.ctx
    try:
        entry, created = await add_to_watchlist(ctx, body.ticker)
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(watchlist_item(entry, ctx.price_cache), status_code=201 if created else 200)


@router.delete("/api/watchlist/{ticker}", status_code=204)
async def delete_watchlist(ticker: str, request: Request) -> Response:
    try:
        removed = await remove_from_watchlist(request.app.state.ctx, ticker)
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"{ticker.strip().upper()} is not on the watchlist"
        )
    return Response(status_code=204)

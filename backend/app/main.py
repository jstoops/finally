"""FastAPI application: API routes, SSE stream, static frontend (PLAN §3).

Run from `backend/`:  uv run uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, db
from app.api import portfolio, system, watchlist
from app.api.chat import router as chat_router
from app.market import MarketDataSource, PriceCache, create_market_data_source, create_stream_router
from app.portfolio import record_snapshot
from app.state import AppState

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 30.0  # seconds (PLAN §7)


def _snapshot(state: AppState) -> None:
    with closing(state.connect()) as conn:
        record_snapshot(conn, state.price_cache)


async def _snapshot_loop(state: AppState, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_snapshot, state)
        except Exception:
            logger.exception("Portfolio snapshot failed")


def create_app(
    db_path: str | None = None,
    static_dir: str | None = None,
    source_factory: Callable[[PriceCache], MarketDataSource] = create_market_data_source,
    snapshot_interval: float = SNAPSHOT_INTERVAL,
) -> FastAPI:
    """Build the app. Arguments override the environment (used by tests)."""
    config.load_env()
    db_path = db_path or config.get_db_path()
    static_dir = static_dir or config.get_static_dir()
    price_cache = PriceCache()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 1. Schema + seed (idempotent)
        db.init_db(db_path)

        # 2. Market data for watchlist ∪ held positions
        with closing(db.connect(db_path)) as conn:
            tickers = {e["ticker"] for e in db.list_watchlist(conn)}
            tickers |= {p["ticker"] for p in db.list_positions(conn)}
        source = source_factory(price_cache)
        await source.start(sorted(tickers))
        state = AppState(db_path=db_path, price_cache=price_cache, market_source=source)
        app.state.ctx = state

        # 3. Initial snapshot, then one every `snapshot_interval` seconds
        _snapshot(state)
        task = asyncio.create_task(_snapshot_loop(state, snapshot_interval), name="snapshots")
        logger.info("FinAlly started (db=%s, %d tickers)", db_path, len(tickers))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await source.stop()

    app = FastAPI(title="FinAlly", lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    app.include_router(create_stream_router(price_cache))
    app.include_router(portfolio.router)
    app.include_router(watchlist.router)
    app.include_router(system.router)
    app.include_router(chat_router)

    # Static frontend last, so /api routes win
    if Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    else:
        logger.info("Static dir %s not found; serving the API only", static_dir)

    return app


app = create_app()

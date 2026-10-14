"""SSE price stream and price-history endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

SSE_INTERVAL = 0.5  # seconds between change checks (PLAN §6)
KEEPALIVE_INTERVAL = 15.0  # seconds of silence before sending a comment line


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Create the market data router (SSE stream + price history).

    Builds a new router per call, bound to `price_cache` (no module-level state).
    """
    router = APIRouter(tags=["market"])

    @router.get("/api/stream/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint for live price updates.

        Sends one event containing all tracked tickers whenever the cache changes
        (checked every ~500ms), in the format:

            data: {"AAPL": {"ticker": "AAPL", "price": 190.50, ...}, ...}

        Includes a retry directive so the browser auto-reconnects on
        disconnection (EventSource built-in behavior).
        """
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    @router.get("/api/prices/{ticker}/history")
    async def price_history(ticker: str) -> dict:
        """Last ~5 minutes of prices for one ticker (empty for untracked)."""
        symbol = ticker.strip().upper()
        return {
            "ticker": symbol,
            "points": [p.to_dict() for p in price_cache.get_history(symbol)],
        }

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = SSE_INTERVAL,
    keepalive: float = KEEPALIVE_INTERVAL,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted price events.

    Sends a frame with all prices whenever the cache version changes, even if the
    cache is now empty (so removing the last ticker clears it on the client).
    Sends a comment line after `keepalive` seconds of silence so idle-timeout
    proxies keep the connection open. Stops when the client disconnects.
    """
    # Tell the client to retry after 1 second if the connection drops
    yield "retry: 1000\n\n"

    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)
    last_version = -1
    last_sent = time.monotonic()

    try:
        while not await request.is_disconnected():
            current_version = price_cache.version
            if current_version != last_version:
                last_version = current_version
                data = {ticker: u.to_dict() for ticker, u in price_cache.get_all().items()}
                yield f"data: {json.dumps(data)}\n\n"
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= keepalive:
                yield ": keep-alive\n\n"
                last_sent = time.monotonic()

            await asyncio.sleep(interval)
    finally:
        # Runs on normal disconnect and on cancellation; CancelledError propagates
        logger.info("SSE client disconnected: %s", client_ip)

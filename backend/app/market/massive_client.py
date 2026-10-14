"""Massive (formerly Polygon.io) REST poller for real market data."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Literal

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import SnapshotMarketType, TickerSnapshot

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

Mode = Literal["live", "eod"]


def pick_price(snap: TickerSnapshot) -> float | None:
    """Best available price in a snapshot, or None.

    Order: last trade → latest minute bar → today's running close → yesterday's
    close. Needs trades entitlement for the first; the day bar is zeroed right
    after the daily reset, so 0 counts as missing.
    """
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    for value in candidates:
        if value:  # skips None and 0
            return float(value)
    return None


def is_not_entitled(err: BadResponse) -> bool:
    """True if Massive rejected the call because the plan lacks this data.

    BadResponse carries only the response body, e.g.
    {"status":"NOT_AUTHORIZED","message":"You are not entitled to this data. ..."}
    A bad key is different: {"status":"ERROR","error":"Unknown API Key"}.
    """
    body = str(err).lower()
    return "not_authorized" in body or "not entitled" in body


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive REST API.

    LIVE mode polls the multi-ticker snapshot endpoint (one call per poll for all
    tickers). Keys without snapshot access (the free Basic plan) switch once to
    EOD mode, which serves the latest end-of-day closes from the grouped-daily
    endpoint.

    Prices are stamped with receipt time, not exchange time: trade times repeat
    between polls and EOD bars are hours old. That keeps both sources on one clock.
    """

    EOD_REFRESH_SECONDS = 3600.0  # re-fetch grouped daily at most hourly
    EOD_RETRY_SECONDS = 300.0  # after a failed/empty lookup, retry sooner
    EOD_LOOKBACK_DAYS = 7  # walk back this far to find the latest trading day
    EOD_PREV_CLOSE_PER_POLL = 2  # /prev fallbacks per poll; protects 5 calls/min

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
        client: RESTClient | None = None,  # injectable for tests
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._client = client
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._mode: Mode = "live"
        # EOD state (only touched by the single in-flight poll)
        self._eod_closes: dict[str, float] = {}
        self._eod_next_refresh = 0.0
        self._eod_unknown: set[str] = set()  # /prev returned nothing: don't retry each poll
        self._warned_missing: set[str] = set()

    @property
    def mode(self) -> Mode:
        return self._mode

    # --- MarketDataSource ---

    async def start(self, tickers: list[str]) -> None:
        if self._client is None:
            self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(dict.fromkeys(t.strip().upper() for t in tickers))

        # Do an immediate first poll so the cache has data before requests arrive
        await self._poll_once()

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval, mode=%s",
            len(self._tickers),
            self._interval,
            self._mode,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added ticker %s (priced on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._warned_missing.discard(ticker)
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Polling ---

    async def _poll_loop(self) -> None:
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """One poll cycle. Never raises (except CancelledError)."""
        if not self._tickers or self._client is None:
            return
        tickers = list(self._tickers)  # the worker thread gets its own copy
        try:
            # The client is synchronous (urllib3, 10 s timeouts, 3 retries):
            # keep it off the event loop.
            prices = await asyncio.to_thread(self._fetch, tickers)
        except BadResponse as e:
            if self._mode == "live" and is_not_entitled(e):
                logger.warning(
                    "Massive key has no snapshot access (Basic plan?): using end-of-day closes"
                )
                self._mode = "eod"
                await self._poll_once()
                return
            logger.error("Massive poll failed: %s", e)
            return
        except Exception:
            logger.exception("Massive poll failed")
            return

        # Re-read: tickers may have been removed while the call was in flight
        tracked = set(self._tickers)
        for ticker, price in prices.items():
            if ticker in tracked:
                self._cache.update(ticker, price)  # receipt-time timestamp

        for ticker in tracked.intersection(tickers) - prices.keys():
            if ticker not in self._warned_missing:
                self._warned_missing.add(ticker)
                logger.warning("Massive returned no price for %s", ticker)

    def _fetch(self, tickers: list[str]) -> dict[str, float]:
        """Runs in a worker thread. Returns {ticker: price}."""
        if self._mode == "live":
            return self._fetch_live(tickers)
        return self._fetch_eod(tickers)

    def _fetch_live(self, tickers: list[str]) -> dict[str, float]:
        snapshots = self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=tickers,
        )
        prices: dict[str, float] = {}
        for snap in snapshots:
            price = pick_price(snap)
            if snap.ticker and price is not None:
                prices[snap.ticker] = price
        return prices

    def _fetch_eod(self, tickers: list[str]) -> dict[str, float]:
        now = time.time()
        if now >= self._eod_next_refresh:
            closes = self._latest_grouped_closes()
            if closes:
                self._eod_closes = closes
                self._eod_unknown.clear()
                self._eod_next_refresh = now + self.EOD_REFRESH_SECONDS
            else:
                self._eod_next_refresh = now + self.EOD_RETRY_SECONDS

        # Rare: a ticker absent from grouped daily. Ask /prev, a few per poll.
        missing = [t for t in tickers if t not in self._eod_closes and t not in self._eod_unknown]
        for ticker in missing[: self.EOD_PREV_CLOSE_PER_POLL]:
            close = self._previous_close(ticker)
            if close:
                self._eod_closes[ticker] = close
            else:
                self._eod_unknown.add(ticker)  # unknown symbol: retried on next refresh

        return {t: self._eod_closes[t] for t in tickers if t in self._eod_closes}

    def _previous_close(self, ticker: str) -> float | None:
        result = self._client.get_previous_close_agg(ticker)
        # The client returns a list of bars (result_key="results"); tolerate a single object
        bar = result[0] if isinstance(result, list) and result else result
        close = getattr(bar, "close", None) if bar else None
        return float(close) if close else None

    def _latest_grouped_closes(self) -> dict[str, float]:
        """Closes for every US stock on the most recent trading day with data.

        Today is empty until EOD data is published; weekends and holidays are
        empty. Weekends are skipped without a call to save free-tier budget.
        """
        day = date.today()
        for _ in range(self.EOD_LOOKBACK_DAYS):
            if day.weekday() < 5:  # Mon–Fri
                aggs = self._client.get_grouped_daily_aggs(day.isoformat(), adjusted=True)
                if aggs:
                    logger.info("Massive EOD: using closes for %s", day.isoformat())
                    return {a.ticker: float(a.close) for a in aggs if a.ticker and a.close}
            day -= timedelta(days=1)
        return {}

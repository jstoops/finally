# Market Data Backend — Implementation Design

**Status:** Implementation reference for `backend/app/market/`.
**Scope:** The unified market data API, the GBM simulator, the Massive (Polygon.io) client, the SSE stream and price-history endpoint, and how the rest of the backend uses them.
**Supersedes:** `archive/MARKET_DATA_DESIGN.md` (that version describes the original build, before the PLAN §6 **[change]** items and before the Massive research).

The code already in `backend/app/market/` works and has 73 passing tests. This document gives the **complete target code**: what exists, plus every change needed to meet `PLAN.md` §5–§8 and to fix the problems found in `MASSIVE_API.md`. An agent should be able to implement the subsystem from this file alone. §13 lists the changes as a checklist.

Related docs (read only if you need background):

| Doc | What it adds |
|---|---|
| `PLAN.md` §6, §8 | The contract: SSE payload, history endpoint, tracked tickers, Chg % |
| `MARKET_INTERFACE.md` | Design rationale for the unified API |
| `MARKET_SIMULATOR.md` | GBM maths, correlation and tuning in depth |
| `MASSIVE_API.md` | Massive endpoints, plans, field names, rate limits |

---

## Table of contents

1. [Architecture](#1-architecture)
2. [Module layout and public API](#2-module-layout-and-public-api)
3. [Data models — `models.py`](#3-data-models--modelspy)
4. [Price cache — `cache.py`](#4-price-cache--cachepy)
5. [Unified interface — `interface.py`](#5-unified-interface--interfacepy)
6. [Seed data — `seed_prices.py`](#6-seed-data--seed_pricespy)
7. [GBM simulator — `simulator.py`](#7-gbm-simulator--simulatorpy)
8. [Massive client — `massive_client.py`](#8-massive-client--massive_clientpy)
9. [Factory — `factory.py`](#9-factory--factorypy)
10. [SSE and history endpoints — `stream.py`](#10-sse-and-history-endpoints--streampy)
11. [Using the subsystem from the app](#11-using-the-subsystem-from-the-app)
12. [Testing](#12-testing)
13. [Change checklist](#13-change-checklist)
14. [Error handling and edge cases](#14-error-handling-and-edge-cases)

---

## 1. Architecture

```
                    env: MASSIVE_API_KEY, MASSIVE_POLL_INTERVAL
                                     │
                       create_market_data_source(cache)
                     ┌───────────────┴────────────────┐
          SimulatorDataSource                  MassiveDataSource
          GBM + Cholesky, every 0.5 s          REST poll, every 15 s (default)
          prices new tickers at once           LIVE (snapshot) or EOD (grouped daily)
                     └───────────────┬────────────────┘
                                     │  cache.update(ticker, price)      ← the ONLY write path
                                     ▼
                                PriceCache
             latest · previous · session open · 5-min history · version
       ┌──────────────┬──────────────┼───────────────────┬──────────────────┐
       ▼              ▼              ▼                   ▼                  ▼
 GET /api/stream/  GET /api/prices/ trade execution   GET /api/portfolio  LLM chat
 prices (SSE)      {t}/history      (fill price)      & watchlist         context
```

Five rules hold the design together:

1. **Push, don't pull.** A source runs its own background task and writes to the `PriceCache`. Request handlers only read the cache. No request ever waits on Massive or the simulator.
2. **One interface, two strategies.** Both sources implement `MarketDataSource`. `create_market_data_source()` picks one from the environment. Nothing downstream knows which is running.
3. **The cache derives everything.** Sources call `cache.update(ticker, price)` and nothing else. The cache computes previous price, direction, session open price, history and the version counter. So the PLAN §6 [change] items live in the cache, and the simulator needs no changes for them.
4. **The app decides which tickers; the source does what it's told.** The tracked set is watchlist ∪ positions (PLAN §6). The app layer computes it and calls `add_ticker`/`remove_ticker` (§11.2).
5. **Background loops never die.** Every error inside a loop is logged and the next cycle retries.

### Threads and the event loop

| Actor | Runs on | Touches |
|---|---|---|
| Simulator loop | event loop | `GBMSimulator` (no lock needed: same thread as `add_ticker`), `PriceCache` |
| Massive poll | event loop, with the blocking HTTP call in `asyncio.to_thread` | `PriceCache` (from the loop thread, after the thread returns) |
| SSE generators, route handlers | event loop | `PriceCache` reads |

`PriceCache` uses a `threading.Lock` anyway. It's cheap, and it keeps the cache safe if a future source writes from a worker thread.

---

## 2. Module layout and public API

```
backend/app/market/
├── __init__.py         public exports
├── models.py           PriceUpdate, PricePoint                         [change]
├── cache.py            PriceCache                                      [change]
├── interface.py        MarketDataSource (ABC)                          unchanged
├── seed_prices.py      seed prices, GBM params, correlation constants  unchanged
├── simulator.py        GBMSimulator, SimulatorDataSource               [small change]
├── massive_client.py   MassiveDataSource, pick_price                   [rewrite]
├── factory.py          create_market_data_source                       [change]
└── stream.py           create_stream_router: SSE + history            [change]
```

`__init__.py`. These are the only names other packages import:

```python
"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate               - Immutable price snapshot (one ticker, one moment)
    PricePoint                - One (timestamp, price) point of history
    PriceCache                - Thread-safe store: latest, open, history, version
    MarketDataSource          - Abstract interface for data providers
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router      - FastAPI router: SSE stream + price history
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PricePoint, PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PricePoint",
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]
```

---

## 3. Data models — `models.py`

Two frozen, slotted dataclasses. `PriceUpdate` gains `open_price` (PLAN §6 [change]). `PricePoint` is new.

```python
"""Data models for market data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of one ticker's latest price.

    Created only by PriceCache.update(), which fills previous_price and open_price.
    """

    ticker: str
    price: float  # rounded to 2 dp
    previous_price: float  # price at the previous update (== price on the first one)
    open_price: float  # session open: first price seen for this ticker this process
    timestamp: float  # Unix seconds (float), when the cache received the price

    @property
    def change(self) -> float:
        """Tick-to-tick absolute change. Used for flash direction only."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Tick-to-tick % change. NOT the UI's Chg % (see session_change_percent)."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def session_change_percent(self) -> float:
        """% change since session open: the UI's "Chg %" (PLAN §6).

        Not in the SSE payload (the frontend computes it from price and open_price);
        provided for server-side consumers such as the LLM portfolio context.
        """
        if self.open_price == 0:
            return 0.0
        return round((self.price - self.open_price) / self.open_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down' or 'flat' relative to the previous update."""
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Exactly the SSE payload fields of PLAN §6, in that order."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One point in a ticker's 5-minute history ring buffer."""

    timestamp: float  # Unix seconds, same clock as PriceUpdate.timestamp
    price: float

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "price": self.price}
```

**Design notes**

- `open_price` is a **required** field placed before `timestamp`. The old `timestamp` default (`default_factory=time.time`) is dropped, because only the cache builds these objects and it always passes a timestamp. The existing `test_models.py` constructors gain `open_price=...` (§13).
- Derived values are properties, not stored fields, so they can never disagree with `price`.
- `frozen=True` lets the cache hand out the same object to many readers with no copying. `slots=True` saves memory: there are up to 600 history points per ticker, although those are `PricePoint`s.

**SSE payload example** (one ticker):

```json
{"ticker": "AAPL", "price": 190.52, "previous_price": 190.41, "open_price": 190.0,
 "timestamp": 1760000000.123, "change": 0.11, "change_percent": 0.0578, "direction": "up"}
```

---

## 4. Price cache — `cache.py`

The single source of truth for prices. One writer (the active source) and many readers.

### 4.1 Behaviour

| Concern | Rule |
|---|---|
| Rounding | `price` is rounded to 2 dp on write, so `previous_price` and `open_price` (copied from earlier writes) are already rounded. |
| Previous price | The prior `price` for that ticker, or `price` itself on the first write (so `direction == "flat"`). |
| Session open | The `price` of the **first** write for that ticker since the process started, or since the ticker was last `remove()`d. Later writes carry it forward. A reset (PLAN §8) doesn't touch the cache, so open prices survive a reset for tickers that stay tracked. |
| Timestamp | Defaults to `time.time()` (receipt time). Sources should **not** pass exchange timestamps: Massive trade times repeat between polls and EOD bars are hours old. Receipt time keeps both sources on one clock. |
| Monotonic history | Per ticker, each new timestamp is forced to be strictly greater than the last (`+1 ms` if the wall clock stepped back or repeated). Lightweight Charts rejects non-ascending times. |
| History | `deque(maxlen=600)` of `PricePoint` per ticker. `get_history()` also drops points older than 300 s. The count cap bounds memory for the 0.5 s simulator. The age filter bounds slow Massive polling (15 s gives ~20 points). |
| Version | Monotonic `int`, bumped on every `update()` **and** every `remove()`, so the SSE stream pushes a frame that no longer contains a removed ticker. Read under the lock. |
| Unknown ticker | `get`/`get_price` → `None`. `get_history` → `[]`. That's how the history endpoint returns `200` with empty `points` for an untracked ticker. |
| Keys | The cache stores whatever key it is given. Callers pass normalized (uppercase, trimmed) tickers. |

### 4.2 Code

```python
"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import Lock

from .models import PricePoint, PriceUpdate


class PriceCache:
    """Latest price, session open price and recent history for each tracked ticker.

    Writers: the active MarketDataSource (simulator or Massive), via update()/remove().
    Readers: SSE stream, history endpoint, portfolio valuation, trade execution, LLM context.
    """

    HISTORY_SECONDS: float = 300.0  # PLAN §6: last 5 minutes
    HISTORY_MAX_POINTS: int = 600  # 5 min at 500 ms; hard cap on memory per ticker

    def __init__(
        self,
        history_seconds: float = HISTORY_SECONDS,
        history_max_points: int = HISTORY_MAX_POINTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._history_seconds = history_seconds
        self._history_max_points = history_max_points
        self._clock = clock  # injectable for tests
        self._prices: dict[str, PriceUpdate] = {}
        self._history: dict[str, deque[PricePoint]] = {}
        self._lock = Lock()
        self._version = 0

    # --- Writes ---

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a price for `ticker` and return the new PriceUpdate.

        Sets open_price on the first update for the ticker, carries it forward
        afterwards, appends to the history buffer and bumps the version.
        """
        price = round(float(price), 2)
        with self._lock:
            ts = timestamp if timestamp is not None else self._clock()
            prev = self._prices.get(ticker)
            if prev is not None and ts <= prev.timestamp:
                ts = prev.timestamp + 0.001  # keep history strictly ascending

            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                open_price=prev.open_price if prev else price,
                timestamp=ts,
            )
            self._prices[ticker] = update

            history = self._history.get(ticker)
            if history is None:
                history = self._history[ticker] = deque(maxlen=self._history_max_points)
            history.append(PricePoint(timestamp=ts, price=price))

            self._version += 1
            return update

    def remove(self, ticker: str) -> None:
        """Forget `ticker` entirely: latest price, session open and history."""
        with self._lock:
            existed = self._prices.pop(ticker, None) is not None
            self._history.pop(ticker, None)
            if existed:
                self._version += 1  # SSE pushes a frame without the ticker

    # --- Reads ---

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        """Shallow copy of all latest prices (values are immutable)."""
        with self._lock:
            return dict(self._prices)

    def get_history(self, ticker: str) -> list[PricePoint]:
        """Points from the last HISTORY_SECONDS, oldest first. [] if unknown."""
        cutoff = self._clock() - self._history_seconds
        with self._lock:
            history = self._history.get(ticker)
            if not history:
                return []
            return [p for p in history if p.timestamp >= cutoff]

    @property
    def version(self) -> int:
        """Monotonic change counter for SSE change detection."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Memory:** 600 points × ~100 bytes ≈ 60 KB per ticker, so about 0.6 MB for the default watchlist. `get_history` copies at most 600 small objects, which is fine for an endpoint called on ticker selection.

### 4.3 Example

```python
cache = PriceCache()
cache.update("AAPL", 190.00)        # open=190.00, previous=190.00, direction="flat"
cache.update("AAPL", 190.25)        # open=190.00, previous=190.00, direction="up"
u = cache.update("AAPL", 189.80)    # open=190.00, previous=190.25, direction="down"

u.change                  # -0.45   (tick to tick)
u.session_change_percent  # -0.1053 (the UI's Chg %)
[p.price for p in cache.get_history("AAPL")]   # [190.0, 190.25, 189.8]

cache.remove("AAPL")
cache.update("AAPL", 200.00)        # new session: open=200.00, history=[200.0]
```

---

## 5. Unified interface — `interface.py`

**Unchanged.** Shown here because it is the contract both sources implement.

```python
class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never asks the source for prices: it reads the cache.
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing prices for `tickers` and start the background task.

        Call exactly once. Should leave the cache populated before returning
        (simulator: always; Massive: if the first poll succeeds). Must NOT raise
        because of a remote failure (bad key, network down): log and keep running.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task. Idempotent. No cache writes afterwards."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start pricing `ticker`. No-op if already tracked.

        Simulator: priced immediately. Massive: priced on the next poll.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop pricing `ticker` and remove it from the PriceCache. No-op if unknown."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers."""
```

### Contract details both implementations must honour

| Topic | Rule |
|---|---|
| Ticker format | The app normalizes and validates tickers (`^[A-Z][A-Z0-9.]{0,9}$`, PLAN §7) before calling. Sources still `.strip().upper()` defensively. |
| Concurrency | `add_ticker`/`remove_ticker` don't await I/O. They run to completion on the event loop, so they can't interleave with each other or with a simulator step. |
| Removal race | A Massive poll may be in flight when a ticker is removed. The source must not write a price for a ticker that is no longer tracked when the poll returns. |
| Before `start` | `add_ticker` before `start` is a no-op for the simulator. The app always starts the source in `lifespan` before serving requests, so this never happens in practice. |
| Shutdown | After `stop()` returns, the source never writes to the cache again. |

### Usage

```python
cache = PriceCache()
source = create_market_data_source(cache)            # unstarted
await source.start(["AAPL", "GOOGL", "MSFT"])        # cache has prices (simulator)
await source.add_ticker("PYPL")                      # simulator: cache.get("PYPL") is set now
await source.remove_ticker("GOOGL")                  # gone from source and cache
source.get_tickers()                                 # ["AAPL", "MSFT", "PYPL"]
await source.stop()
```

---

## 6. Seed data — `seed_prices.py`

**Unchanged.** Plain constants, no logic.

```python
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00, "AMZN": 185.00, "TSLA": 250.00,
    "NVDA": 800.00, "META": 500.00, "JPM": 195.00, "V": 280.00, "NFLX": 600.00,
}

# sigma: annualized volatility; mu: annualized drift
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # high volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # high volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},   # low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},     # low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
}

DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}  # any other ticker

CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR = 0.6
INTRA_FINANCE_CORR = 0.5
CROSS_GROUP_CORR = 0.3  # between sectors, and for unknown tickers
TSLA_CORR = 0.3         # TSLA does its own thing
```

To add a well-known ticker with a realistic price, add one line to `SEED_PRICES` and, optionally, to `TICKER_PARAMS` and a correlation group.

---

## 7. GBM simulator — `simulator.py`

The default source. The maths is explained in `MARKET_SIMULATOR.md`. This section gives the code.

### 7.1 Model

Per ticker, per 500 ms tick:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt + σ·√Δt·Z )      Δt = 0.5 / (252 · 6.5 · 3600) ≈ 8.48e-8
Z = L · z,  z ~ N(0, I),  L = cholesky(C)            C[i][j] from sector groups (§6)
then with probability 0.001:  S ← S · (1 ± U(0.02, 0.05))     a random "event"
```

One AAPL tick is about ±1¢. With 10 tickers at 2 ticks/s, an event happens somewhere on the board about every 50 s.

### 7.2 `GBMSimulator`: the pure, synchronous core

The existing class stays as is, except for **one change**: unknown tickers get a seed price derived from the symbol rather than from the global RNG. So `PYPL` restarts at the same price after a container restart, instead of jumping away from a held position's `avg_cost`.

```python
class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices. No I/O, no asyncio."""

    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}  # full precision; only output is rounded
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None
        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance every ticker one tick. Returns {ticker: price rounded to 2 dp}. Hot path."""
        n = len(self._tickers)
        if n == 0:
            return {}
        z = np.random.standard_normal(n)
        if self._cholesky is not None:  # None when n == 1
            z = self._cholesky @ z

        result: dict[str, float] = {}
        sqrt_dt = math.sqrt(self._dt)
        for i, ticker in enumerate(self._tickers):
            mu = self._params[ticker]["mu"]
            sigma = self._params[ticker]["sigma"]
            self._prices[ticker] *= math.exp((mu - 0.5 * sigma**2) * self._dt + sigma * sqrt_dt * z[i])

            if random.random() < self._event_prob:
                shock = random.uniform(0.02, 0.05) * random.choice((-1, 1))
                self._prices[ticker] *= 1 + shock
                logger.debug("Random event on %s: %+.1f%%", ticker, shock * 100)

            result[ticker] = round(self._prices[ticker], 2)
        return result

    def add_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add without rebuilding Cholesky (batch init)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker) or _unknown_seed_price(ticker)  # [change]
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild L whenever the ticker set changes (not per tick). O(n³), n < 50."""
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        tech, finance = CORRELATION_GROUPS["tech"], CORRELATION_GROUPS["finance"]
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR


def _unknown_seed_price(ticker: str) -> float:  # [change: new helper]
    """Deterministic seed in [50, 300) for tickers without a SEED_PRICES entry."""
    return round(random.Random(ticker).uniform(50.0, 300.0), 2)
```

> **Why Cholesky can't fail with these constants.** Every off-diagonal entry is in [0.3, 0.6] and intra-group values are ≥ the cross-group floor, so the matrix is positive definite (smallest eigenvalue ≥ 0.4). If someone edits the constants, keep intra-group ρ ≥ cross-group ρ.

### 7.3 `SimulatorDataSource`: the async adapter

**Unchanged.** The cache supplies open price and history, so no change is needed for PLAN §6.

```python
class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by GBMSimulator, stepping every `update_interval` seconds."""

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)
        # Seed the cache so SSE, trades and the first snapshot have prices immediately
        for ticker in self._sim.get_tickers():
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)  # PLAN §6: "priced immediately"
            if price is not None and ticker not in self._cache:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    for ticker, price in self._sim.step().items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")  # never kill the loop
            await asyncio.sleep(self._interval)
```

Two small hardening edits (marked in §13): normalize the ticker in `add_ticker`/`remove_ticker`, and only seed the cache in `add_ticker` when the ticker isn't already cached. Without the second, re-adding a tracked ticker would write its *current* simulator price a second time, which is harmless but adds a duplicate history point.

**Why the step runs on the event loop thread:** a step for tens of tickers takes microseconds. `add_ticker` runs on the same thread, so the simulator needs no lock. Interval drift doesn't matter, because SSE pushes on version change, not on wall-clock alignment.

### 7.4 Example timeline

```python
cache = PriceCache()
sim = SimulatorDataSource(cache)
await sim.start(["AAPL", "TSLA"])     # t=0.0  AAPL 190.00 (open), TSLA 250.00 (open)
await asyncio.sleep(1.0)              # t≈1.0  2 ticks: AAPL ~190.01, history = 3 points
await sim.add_ticker("PYPL")          #        PYPL priced now at its deterministic seed
cache.get("PYPL").open_price          #        == _unknown_seed_price("PYPL")
await sim.remove_ticker("TSLA")       #        TSLA gone from sim, cache and next SSE frame
await sim.stop()
```

---

## 8. Massive client — `massive_client.py`

Used when `MASSIVE_API_KEY` is set. This is a **rewrite** of the current module, for three reasons found in `MASSIVE_API.md`:

1. **Bug:** the current code reads `snap.last_trade.timestamp`. The client model has no such attribute; the field is `sip_timestamp`, in nanoseconds. Against the real API every snapshot raises `AttributeError`, gets skipped, and **no price is ever written**. The `MagicMock` fixtures in `test_massive.py` hid this.
2. **Free keys can't use snapshots.** The Basic plan has no snapshot entitlement and only end-of-day data. The client must fall back to the grouped-daily endpoint.
3. `last_trade` is absent on plans without trades entitlement, and `day` is zeroed overnight. Price selection needs a fallback chain.

### 8.1 Modes

```
                 ┌── snapshot OK ──────────────► LIVE: get_snapshot_all(STOCKS, tickers)
start() → poll ──┤                                1 call per poll, every MASSIVE_POLL_INTERVAL s
                 └── BadResponse NOT_AUTHORIZED ─► EOD:  get_grouped_daily_aggs(latest trading day)
                     (once; logged at WARNING)          1 call per hour, kept in memory; each poll
                                                         reads the in-memory closes (0 calls)
```

| | LIVE | EOD |
|---|---|---|
| Plans | Starter, Developer (15-min delayed), Advanced (real-time) | Basic (free) |
| Network calls | 1 per poll, regardless of ticker count | 1 grouped call per hour (+ walk-back on weekends/holidays) + at most 2 `/prev` calls per poll for tickers missing from the grouped data |
| New ticker priced | Next poll (≤ 15 s) | Next poll, usually with no API call (the grouped data has ~10k tickers) |
| Price movement | Changes each poll | Flat (yesterday's close). The chart is a flat line and Chg % is 0. That is honest for an EOD feed. |

The mode only switches LIVE → EOD, and only on an entitlement error. A bad key (401), rate limit (429), server error or network failure is logged and retried next interval in the same mode.

### 8.2 Choosing the price from a snapshot

First non-empty value, best first:

| # | Attribute | Notes |
|---|---|---|
| 1 | `snap.last_trade.price` | Actual last print. Needs trades entitlement. |
| 2 | `snap.min.close` | Latest minute bar |
| 3 | `snap.day.close` | Today's running close. Zero right after the 3:30 AM ET reset. |
| 4 | `snap.prev_day.close` | Yesterday's close: the overnight fallback |

"Empty" means `None` **or `0`**, because overnight the `day` bar is zeroed rather than removed.

### 8.3 Code

```python
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
    """Best available price in a snapshot (see table in §8.2), or None."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    for value in candidates:
        if value:  # skips None and 0 (the day bar is zeroed right after the daily reset)
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
            self._client = RESTClient(api_key=self._api_key)  # pass the key explicitly
        self._tickers = list(dict.fromkeys(t.strip().upper() for t in tickers))
        await self._poll_once()  # populate the cache before the app serves requests
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval, mode=%s",
            len(self._tickers), self._interval, self._mode,
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
            logger.info("Massive: added %s (priced on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.strip().upper()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._warned_missing.discard(ticker)
        self._cache.remove(ticker)
        logger.info("Massive: removed %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Polling ---

    async def _poll_loop(self) -> None:
        """First poll already ran in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """One poll cycle. Never raises (except CancelledError)."""
        if not self._tickers or self._client is None:
            return
        tickers = list(self._tickers)
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

        tracked = set(self._tickers)  # re-read: tickers may have changed during the call
        for ticker, price in prices.items():
            if ticker in tracked:  # ignore tickers removed while the call was in flight
                self._cache.update(ticker, price)  # receipt-time timestamp (§4.1)

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
            tickers=tickers,  # joined with "," by the client; case-sensitive → uppercase
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
            bars = self._client.get_previous_close_agg(ticker)
            if bars and bars[0].close:
                self._eod_closes[ticker] = float(bars[0].close)
            else:
                self._eod_unknown.add(ticker)  # unknown symbol: retried on next refresh

        return {t: self._eod_closes[t] for t in tickers if t in self._eod_closes}

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
```

### 8.4 Rate-limit budget (free Basic plan, 5 calls/min)

| Moment | Calls |
|---|---|
| First poll on startup | 1 snapshot (rejected) + 1–2 grouped (today empty → previous weekday; holidays add 1) = **2–3** |
| Each later poll | **0**, unless a ticker is missing from the grouped data (≤ 2 `/prev` calls, once per unknown ticker per hour) |
| Hourly refresh | 1–2 |

Paid plans make one snapshot call per poll: 4 calls/min at the 15 s default, or 30/min at `MASSIVE_POLL_INTERVAL=2`. A failed call costs up to 3 automatic client retries for 429/5xx, then is logged.

### 8.5 Behaviour in each situation

| Situation | Result |
|---|---|
| Valid paid key, market open | Prices update every poll. Chg % is measured from the first price this process saw. |
| Valid paid key, overnight | `prev_day.close` (or the last minute bar), flat until pre-market. |
| Free key | One WARNING, then EOD closes. Flat prices. Trades work at yesterday's close. |
| Bad key (401) | ERROR logged every poll. Cache stays empty, so the watchlist shows `null` prices and trades get "No price available…". The app still runs. |
| Network down at startup | `start()` logs and returns. The loop keeps retrying. |
| Unknown symbol added (`ZZZZ`) | Absent from the response. Logged once. No cache entry, so trades are rejected (PLAN §7). |

---

## 9. Factory — `factory.py`

Adds `MASSIVE_POLL_INTERVAL` (PLAN §5/§6 [change]).

```python
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)

DEFAULT_MASSIVE_POLL_INTERVAL = 15.0  # suits the free tier's 5 calls/min
MIN_MASSIVE_POLL_INTERVAL = 1.0


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Return an UNSTARTED source chosen from the environment.

    - MASSIVE_API_KEY set and non-blank → MassiveDataSource, polling every
      MASSIVE_POLL_INTERVAL seconds (default 15, minimum 1)
    - otherwise → SimulatorDataSource
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        interval = _env_float(
            "MASSIVE_POLL_INTERVAL", DEFAULT_MASSIVE_POLL_INTERVAL, MIN_MASSIVE_POLL_INTERVAL
        )
        logger.info("Market data source: Massive API (poll every %.1fs)", interval)
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)

    logger.info("Market data source: GBM simulator")
    return SimulatorDataSource(price_cache=price_cache)


def _env_float(name: str, default: float, minimum: float) -> float:
    """Parse a float env var. Blank → default; invalid → default + warning; clamp to minimum."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%s is below the minimum; using %s", name, raw, minimum)
        return minimum
    return value
```

| `MASSIVE_API_KEY` | `MASSIVE_POLL_INTERVAL` | Result |
|---|---|---|
| unset / `""` / `"  "` | ignored | `SimulatorDataSource` |
| `"abc123"` | unset / `""` | `MassiveDataSource`, 15 s |
| `"abc123"` | `"5"` | 5 s |
| `"abc123"` | `"0.2"` | 1 s (clamped, warning) |
| `"abc123"` | `"fast"` | 15 s (warning) |

---

## 10. SSE and history endpoints — `stream.py`

Two endpoints on one router. Changes from today:

- The router is created **inside** the factory. The current module-level `router` means a second call (e.g. in tests) registers the routes twice.
- New `GET /api/prices/{ticker}/history` (PLAN §8).
- A keep-alive comment every 15 s of silence. That happens in EOD mode, or when the watchlist is empty. It stops idle-timeout proxies from cutting the connection. `EventSource` ignores comment lines.
- A frame is sent on every version change, even when the cache is empty (`data: {}`), so removing the last ticker clears it on the client.

### 10.1 Wire format

```
retry: 1000

data: {"AAPL": {"ticker": "AAPL", "price": 190.52, "previous_price": 190.41, "open_price": 190.0, "timestamp": 1760000000.123, "change": 0.11, "change_percent": 0.0578, "direction": "up"}, "GOOGL": {...}}

data: {"AAPL": {...}, "GOOGL": {...}}

: keep-alive

```

Every frame holds **all** tracked tickers. A ticker that didn't change since the last frame repeats its previous `timestamp`, which the frontend uses to skip duplicate chart points (§11.5).

### 10.2 Code

```python
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
    """Build a NEW router bound to `price_cache` (no module-level state)."""
    router = APIRouter(prefix="/api", tags=["market"])

    @router.get("/stream/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """Long-lived SSE stream of all tracked prices (PLAN §6)."""
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    @router.get("/prices/{ticker}/history")
    async def price_history(ticker: str) -> dict:
        """Last ~5 minutes of prices for one ticker. Empty points if untracked (PLAN §8)."""
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
    """Yield SSE frames until the client disconnects."""
    yield "retry: 1000\n\n"  # browser reconnects 1 s after a drop

    client = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client)
    last_version = -1
    last_sent = time.monotonic()

    try:
        while not await request.is_disconnected():
            version = price_cache.version
            if version != last_version:
                last_version = version
                payload = {t: u.to_dict() for t, u in price_cache.get_all().items()}
                yield f"data: {json.dumps(payload)}\n\n"
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= keepalive:
                yield ": keep-alive\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("SSE client disconnected: %s", client)
```

**Why poll the version instead of an event per update?** The simulator writes 10+ updates per tick. Polling a counter every 500 ms coalesces them into one frame per tick per client, costs one integer compare when idle, and needs no per-client queues.

### 10.3 History endpoint examples

```
GET /api/prices/aapl/history
200 {"ticker": "AAPL", "points": [{"timestamp": 1760000000.0, "price": 190.41},
                                  {"timestamp": 1760000000.5, "price": 190.52}, ...]}   ≤ 600 points

GET /api/prices/ZZZZ/history
200 {"ticker": "ZZZZ", "points": []}
```

The path parameter isn't validated against the ticker regex: any unknown string just returns empty points, as PLAN §8 specifies.

---

## 11. Using the subsystem from the app

The app layer (outside `app/market/`) owns the lifecycle, the tracked-ticker rule and all reads. The DB helpers named below (`db.watchlist_tickers()` etc.) belong to `app/db/` and are only sketched.

### 11.1 Startup and shutdown — `app/main.py`

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, create_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Schema + seed (PLAN §7), idempotent
    db.init_db()

    # 2. Market data, tracking watchlist ∪ positions (PLAN §3, §6)
    cache = PriceCache()
    source = create_market_data_source(cache)
    with db.connect() as conn:
        tracked = db.watchlist_tickers(conn) | db.position_tickers(conn)
    await source.start(sorted(tracked))
    app.state.price_cache = cache
    app.state.market = source
    app.include_router(create_stream_router(cache))

    # 3. Initial snapshot, then every 30 s (PLAN §3, §7)
    await portfolio.record_snapshot(cache)
    snapshot_task = asyncio.create_task(portfolio.snapshot_loop(cache, every=30.0))

    try:
        yield
    finally:
        snapshot_task.cancel()
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(api_router)  # portfolio, watchlist, chat, health
# Mount static files LAST so /api/* routes win:
# app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

Including the stream router inside `lifespan` works because Starlette resolves routes per request, and `lifespan` finishes before the first request. To include it at import time instead, use `app.state` through a dependency:

```python
from fastapi import Request

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_market(request: Request) -> MarketDataSource:
    return request.app.state.market
```

Route handlers take these with `Depends(get_price_cache)` and `Depends(get_market)`.

### 11.2 Tracked tickers = watchlist ∪ positions — `app/services/tracking.py`

Keep the PLAN §6 rule in one place:

```python
from app.market import MarketDataSource


async def on_watchlist_add(source: MarketDataSource, ticker: str) -> None:
    await source.add_ticker(ticker)  # no-op if already tracked (e.g. held)


async def on_watchlist_remove(conn, source: MarketDataSource, ticker: str) -> None:
    if not db.has_position(conn, ticker):  # keep held tickers priced
        await source.remove_ticker(ticker)


async def on_position_closed(conn, source: MarketDataSource, ticker: str) -> None:
    """Call after a sell deletes the position row (dust rule, PLAN §7)."""
    if not db.on_watchlist(conn, ticker):
        await source.remove_ticker(ticker)


async def resync(conn, source: MarketDataSource) -> None:
    """Call after POST /api/reset (and any time the sets might have drifted)."""
    wanted = db.watchlist_tickers(conn) | db.position_tickers(conn)
    current = set(source.get_tickers())
    for ticker in sorted(current - wanted):
        await source.remove_ticker(ticker)
    for ticker in sorted(wanted - current):
        await source.add_ticker(ticker)
```

Call these **after** the DB transaction commits, so the source never runs ahead of the database. A buy can't create an untracked position: the trade rule rejects any ticker without a cached price, and only tracked tickers have one.

### 11.3 Reading prices

| Consumer | Call | Notes |
|---|---|---|
| Trade execution (PLAN §7) | `cache.get_price(t)` | `None` → `400 "No price available for {t}. Add it to your watchlist first."` |
| `GET /api/portfolio` | `cache.get_price(t)` | `None` → fall back to `avg_cost` (PLAN §8) |
| `GET /api/watchlist` | `cache.get(t)` | `price`/`open_price` from the update, or both `null` |
| LLM context (PLAN §9) | `cache.get_all()` | Use `session_change_percent` for "today's" move |
| Snapshots | `cache.get_price(t)` | Same fallback as `/api/portfolio` |

```python
# Trade execution
price = cache.get_price(ticker)
if price is None:
    raise TradeError(f"No price available for {ticker}. Add it to your watchlist first.")

# Watchlist row
u = cache.get(ticker)
row = {"ticker": ticker, "price": u.price if u else None,
       "open_price": u.open_price if u else None, "added_at": added_at}

# LLM context line
for t, u in sorted(cache.get_all().items()):
    lines.append(f"{t}: ${u.price:.2f} ({u.session_change_percent:+.2f}% since open)")
```

### 11.4 Watchlist route sketch

```python
@router.post("/watchlist", status_code=201)
async def add_to_watchlist(body: WatchlistAdd, response: Response,
                           market: MarketDataSource = Depends(get_market),
                           cache: PriceCache = Depends(get_price_cache)):
    ticker = normalize_ticker(body.ticker)  # 400 on malformed (PLAN §7 regex)
    with db.connect() as conn:
        entry, created = db.add_watchlist(conn, ticker)
    await tracking.on_watchlist_add(market, ticker)
    if not created:
        response.status_code = 200  # idempotent (PLAN §8)
    u = cache.get(ticker)  # simulator: already priced; Massive: None until next poll
    return {**entry, "price": u.price if u else None, "open_price": u.open_price if u else None}
```

### 11.5 Frontend contract notes

These are for the frontend agent, collected here because they follow from this design:

- On ticker selection, `GET /api/prices/{t}/history` and `setData(points)`. Then append SSE points for that ticker **only if `timestamp` > the last point's timestamp**: frames repeat unchanged tickers, and Massive updates only every poll.
- Timestamps are fractional Unix seconds, 0.5 s apart. Lightweight Charts needs strictly ascending times; the cache guarantees that within one ticker's history.
- Chg % = `(price - open_price) / open_price * 100`. Flash direction comes from `direction`.
- A ticker missing from a frame is no longer tracked. Drop its live price (and stop its sparkline).

---

## 12. Testing

Unit tests live in `backend/tests/market/`. Add `httpx` to the dev extras for the endpoint tests (FastAPI's `TestClient` needs it):

```toml
[project.optional-dependencies]
dev = ["pytest>=8.3.0", "pytest-asyncio>=0.24.0", "pytest-cov>=5.0.0", "ruff>=0.7.0", "httpx>=0.27.0"]
```

### 12.1 Cache: open price, history, version — `test_cache.py` (add)

```python
from app.market.cache import PriceCache


class FakeClock:
    def __init__(self, t: float = 1_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_open_price_set_once_and_carried_forward():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.0)
    u = cache.update("AAPL", 189.0)
    assert u.open_price == 190.0
    assert u.previous_price == 191.0
    assert u.session_change_percent == round((189 - 190) / 190 * 100, 4)


def test_remove_starts_new_session_and_clears_history():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("AAPL")
    assert cache.get_history("AAPL") == []
    assert cache.update("AAPL", 200.0).open_price == 200.0


def test_history_age_limit():
    clock = FakeClock()
    cache = PriceCache(clock=clock)
    cache.update("AAPL", 1.0)          # t=1000
    clock.t += 301
    cache.update("AAPL", 2.0)          # t=1301
    assert [p.price for p in cache.get_history("AAPL")] == [2.0]


def test_history_count_limit():
    clock = FakeClock()
    cache = PriceCache(history_max_points=5, clock=clock)
    for i in range(10):
        clock.t += 0.5
        cache.update("AAPL", 100.0 + i)
    assert [p.price for p in cache.get_history("AAPL")] == [105.0, 106.0, 107.0, 108.0, 109.0]


def test_timestamps_strictly_increase():
    cache = PriceCache()
    a = cache.update("AAPL", 1.0, timestamp=50.0)
    b = cache.update("AAPL", 1.0, timestamp=50.0)   # repeated
    c = cache.update("AAPL", 1.0, timestamp=10.0)   # clock stepped back
    assert a.timestamp < b.timestamp < c.timestamp


def test_timestamp_zero_is_respected():
    assert PriceCache().update("AAPL", 1.0, timestamp=0.0).timestamp == 0.0


def test_remove_bumps_version_only_if_present():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    v = cache.version
    cache.remove("AAPL")
    assert cache.version == v + 1
    cache.remove("AAPL")
    assert cache.version == v + 1


def test_unknown_ticker_history_is_empty():
    assert PriceCache().get_history("ZZZZ") == []
```

### 12.2 Models — `test_models.py` (update)

Every existing `PriceUpdate(...)` call gains `open_price=...`. Then add:

```python
def test_to_dict_includes_open_price():
    u = PriceUpdate(ticker="AAPL", price=190.5, previous_price=190.0, open_price=189.0, timestamp=1.0)
    assert list(u.to_dict()) == [
        "ticker", "price", "previous_price", "open_price",
        "timestamp", "change", "change_percent", "direction",
    ]
    assert u.to_dict()["open_price"] == 189.0
```

### 12.3 Simulator — `test_simulator.py` (add)

```python
from app.market.simulator import GBMSimulator, _unknown_seed_price


def test_unknown_seed_is_deterministic_and_in_range():
    a = GBMSimulator(["PYPL"]).get_price("PYPL")
    b = GBMSimulator(["PYPL"]).get_price("PYPL")
    assert a == b == _unknown_seed_price("PYPL")
    assert 50.0 <= a < 300.0


def test_full_default_watchlist_cholesky():
    sim = GBMSimulator(["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"])
    assert sim._cholesky.shape == (10, 10)
    assert len(sim.step()) == 10
```

### 12.4 Factory — `test_factory.py` (add)

```python
import pytest

from app.market.cache import PriceCache
from app.market.factory import create_market_data_source


@pytest.mark.parametrize(("raw", "expected"), [(None, 15.0), ("", 15.0), ("5", 5.0),
                                               ("0.2", 1.0), ("fast", 15.0)])
def test_massive_poll_interval(monkeypatch, raw, expected):
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    if raw is None:
        monkeypatch.delenv("MASSIVE_POLL_INTERVAL", raising=False)
    else:
        monkeypatch.setenv("MASSIVE_POLL_INTERVAL", raw)
    assert create_market_data_source(PriceCache())._interval == expected
```

### 12.5 Massive — `test_massive.py` (rewrite)

Build fixtures with the **real** model classes. A `MagicMock` happily returns a value for `last_trade.timestamp`, which is exactly how the current bug went unnoticed.

```python
from unittest.mock import MagicMock

import pytest
from massive.exceptions import BadResponse
from massive.rest.models import GroupedDailyAgg, TickerSnapshot

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource, pick_price


def snap(ticker, *, trade=None, minute=None, day=None, prev=None) -> TickerSnapshot:
    data = {"ticker": ticker}
    if trade is not None:
        data["lastTrade"] = {"p": trade, "t": 1_760_000_000_000_000_000}
    if minute is not None:
        data["min"] = {"c": minute}
    if day is not None:
        data["day"] = {"c": day}
    if prev is not None:
        data["prevDay"] = {"c": prev}
    return TickerSnapshot.from_dict(data)


def source_with(client) -> tuple[MassiveDataSource, PriceCache]:
    cache = PriceCache()
    return MassiveDataSource("k", cache, poll_interval=60, client=client), cache


@pytest.mark.parametrize(("kwargs", "expected"), [
    ({"trade": 190.5, "minute": 190.4, "day": 190.3, "prev": 189.0}, 190.5),
    ({"minute": 190.4, "day": 190.3, "prev": 189.0}, 190.4),
    ({"day": 190.3, "prev": 189.0}, 190.3),
    ({"day": 0, "prev": 189.0}, 189.0),            # day bar zeroed overnight
    ({}, None),
])
def test_pick_price_fallback_order(kwargs, expected):
    assert pick_price(snap("AAPL", **kwargs)) == expected


async def test_live_poll_updates_cache():
    client = MagicMock()
    client.get_snapshot_all.return_value = [snap("AAPL", trade=190.5), snap("MSFT", prev=420.0)]
    source, cache = source_with(client)
    await source.start(["AAPL", "MSFT"])
    try:
        assert cache.get_price("AAPL") == 190.5
        assert cache.get_price("MSFT") == 420.0
        assert source.mode == "live"
    finally:
        await source.stop()


async def test_not_entitled_switches_to_eod_once():
    client = MagicMock()
    client.get_snapshot_all.side_effect = BadResponse(
        '{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data."}')
    client.get_grouped_daily_aggs.return_value = [
        GroupedDailyAgg(ticker="AAPL", close=190.0), GroupedDailyAgg(ticker="PYPL", close=70.0)]
    source, cache = source_with(client)
    await source.start(["AAPL"])
    try:
        assert source.mode == "eod"
        assert cache.get_price("AAPL") == 190.0
        await source.add_ticker("PYPL")
        await source._poll_once()                     # served from memory: no new grouped call
        assert cache.get_price("PYPL") == 70.0
        assert client.get_snapshot_all.call_count == 1
    finally:
        await source.stop()


async def test_bad_key_stays_live_and_does_not_raise():
    client = MagicMock()
    client.get_snapshot_all.side_effect = BadResponse('{"status":"ERROR","error":"Unknown API Key"}')
    source, cache = source_with(client)
    await source.start(["AAPL"])
    try:
        assert source.mode == "live"
        assert cache.get_price("AAPL") is None
    finally:
        await source.stop()


async def test_ticker_removed_mid_poll_is_not_written():
    client = MagicMock()
    source, cache = source_with(client)
    source._tickers = ["AAPL", "TSLA"]

    def fetch(market_type, tickers):
        source._tickers.remove("TSLA")                # simulate remove_ticker during the call
        return [snap("AAPL", trade=1.0), snap("TSLA", trade=2.0)]

    client.get_snapshot_all.side_effect = fetch
    await source._poll_once()
    assert "AAPL" in cache and "TSLA" not in cache
```

(`GroupedDailyAgg` is a plain dataclass with optional fields, so it can be built with keywords.)

### 12.6 Stream and history endpoints — `test_stream.py` (new)

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class FakeRequest:
    """Disconnects after `frames` checks."""
    client = None

    def __init__(self, frames: int):
        self.left = frames

    async def is_disconnected(self) -> bool:
        self.left -= 1
        return self.left < 0


async def test_first_frames():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    frames = [f async for f in _generate_events(cache, FakeRequest(1), interval=0)]
    assert frames[0] == "retry: 1000\n\n"
    assert frames[1].startswith('data: {"AAPL": {"ticker": "AAPL", "price": 190.0')


async def test_no_frame_without_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    frames = [f async for f in _generate_events(cache, FakeRequest(3), interval=0, keepalive=999)]
    assert len(frames) == 2                           # retry + one data frame


def test_history_endpoint():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    app = FastAPI()
    app.include_router(create_stream_router(cache))
    client = TestClient(app)
    body = client.get("/api/prices/aapl/history").json()
    assert body["ticker"] == "AAPL" and body["points"][0]["price"] == 190.0
    assert client.get("/api/prices/ZZZZ/history").json() == {"ticker": "ZZZZ", "points": []}


def test_router_factory_is_independent():
    a, b = create_stream_router(PriceCache()), create_stream_router(PriceCache())
    assert len(a.routes) == len(b.routes) == 2
```

### 12.7 Tracked-ticker rule (app layer, PLAN §12)

These live with the app tests once `tracking.py` exists:

- Removing a **held** ticker from the watchlist keeps it in `source.get_tickers()` and in the cache.
- Selling a ticker that is **not** on the watchlist down to zero removes it from the source and the cache.
- `resync` after a reset leaves exactly the default watchlist tracked.

### 12.8 Running

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest tests/market -v
uv run --extra dev pytest --cov=app.market
uv run --extra dev ruff check app/ tests/
```

---

## 13. Change checklist

In implementation order. Each step leaves the suite green.

| # | File | Change | Why |
|---|---|---|---|
| 1 | `models.py` | Add required `open_price` field (after `previous_price`), `session_change_percent`, `open_price` in `to_dict()`. Drop the `timestamp` default. Add `PricePoint`. | PLAN §6 [change] |
| 2 | `tests/market/test_models.py` | Pass `open_price=` in constructors. Add the `to_dict` key-order test. | follows #1 |
| 3 | `cache.py` | Set/carry `open_price`. Per-ticker history deque + `get_history()`. Strictly increasing timestamps. `timestamp is not None` (not `or`). `remove()` clears history and bumps version. `version` read under the lock. Injectable `clock`. | PLAN §6 [change], review §3.4 |
| 4 | `tests/market/test_cache.py` | Tests from §12.1. | PLAN §12 |
| 5 | `simulator.py` | `_unknown_seed_price()` helper. Normalize tickers in `add_ticker`/`remove_ticker`. Skip the re-seed write when already cached. | §7 |
| 6 | `factory.py` | `MASSIVE_POLL_INTERVAL` via `_env_float` (default 15, floor 1). | PLAN §5/§6 [change] |
| 7 | `massive_client.py` | Rewrite per §8.3: `pick_price` fallback, receipt-time stamps, LIVE→EOD switch, grouped-daily closes, removed-mid-poll guard, injectable client. | Bug fix + free-tier support |
| 8 | `tests/market/test_massive.py` | Rewrite per §12.5 with real model classes. | The old mocks hid the bug |
| 9 | `stream.py` | Router created inside the factory. Add the history endpoint. Keep-alive comment. Send frames on every version change. | PLAN §8, review §3.6 |
| 10 | `tests/market/test_stream.py` | New, per §12.6. Add `httpx` to dev extras. | review §4.2 |
| 11 | `__init__.py` | Export `PricePoint`. | §2 |
| 12 | `backend/CLAUDE.md`, `MARKET_DATA_SUMMARY.md` | Document `open_price`, `get_history`, `MASSIVE_POLL_INTERVAL`, the history endpoint and EOD mode. | Keep docs true |

`interface.py` and `seed_prices.py` don't change. `market_data_demo.py` keeps working: it only reads `price`, `previous_price` and `direction`.

### Acceptance criteria

- [ ] `uv run --extra dev pytest` passes and `ruff check` is clean.
- [ ] `curl -N localhost:8000/api/stream/prices` shows `retry: 1000`, then about two frames per second, each with all tracked tickers and an `open_price` field.
- [ ] `curl localhost:8000/api/prices/AAPL/history` returns up to 600 points, oldest first. After 5 minutes of uptime the first point is ~300 s old.
- [ ] Adding `PYPL` (simulator) makes it appear in the very next SSE frame, at the same price after every restart.
- [ ] With a free Massive key: one WARNING about snapshot access, then prices equal the last trading day's closes. No 429s in steady state.
- [ ] With a paid Massive key: prices change between polls. `MASSIVE_POLL_INTERVAL=5` polls every 5 s.

---

## 14. Error handling and edge cases

| Case | Behaviour |
|---|---|
| Empty tracked set at startup | Both sources start fine. SSE sends `data: {}` once, then keep-alives. Adding a ticker starts prices flowing. |
| Trade on a ticker with no cached price | `cache.get_price()` is `None` → `400` "No price available…" (PLAN §7). Only possible in Massive mode before the first successful poll, or for symbols Massive doesn't know. |
| Massive down / bad key at startup | `start()` logs and returns. The app boots. Portfolio valuation falls back to `avg_cost`. |
| Simulator step raises | Logged with traceback. Next tick retries. |
| Ticker removed while a Massive poll is in flight | The result for it is discarded (`tracked` re-read after the thread returns). |
| Ticker removed and re-added | New session: fresh `open_price` and empty history. |
| `POST /api/reset` | The cache isn't cleared. `resync` removes tickers no longer wanted (clearing their open and history) and adds the default ones. Default tickers that stayed tracked keep their session open. |
| Wall clock steps backwards (NTP) | The cache forces timestamps to keep increasing by 1 ms, so the chart never breaks. |
| Many SSE clients | Each client is one coroutine that compares an int every 500 ms and serializes the cache on change. Fine for tens of tabs. |
| Process restart | All in-memory state is lost: session opens reset, history starts empty, simulator prices restart from their seeds. Positions and trades are in SQLite and unaffected. |
| Floating-point drift in the simulator | Internal prices stay full precision. Only published prices are rounded, so rounding never compounds. |

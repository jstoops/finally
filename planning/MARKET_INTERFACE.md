# Market Data Interface: Unified Python API

The design of FinAlly's single Python API for stock prices. It is backed by the **Massive API** when `MASSIVE_API_KEY` is set and by the **GBM simulator** otherwise. Everything downstream (SSE, portfolio valuation, trade execution, chat context, history endpoint) uses one cache and one interface and never knows which source is running.

- API research: `MASSIVE_API.md`. Simulator internals: `MARKET_SIMULATOR.md`. Project contract: `PLAN.md` §6.
- Code: `backend/app/market/`. This document describes the **target** design: the code that exists today plus the PLAN §6 **[change]** items and the Massive fixes found during research. §9 lists exactly what changes.

---

## 1. Design principles

1. **Push, don't pull.** A source runs its own background task and *writes* into a shared `PriceCache`. Consumers only ever *read* the cache. No request handler calls Massive or the simulator.
2. **One interface, two strategies.** `SimulatorDataSource` and `MassiveDataSource` implement the same `MarketDataSource` ABC. A factory picks one from the environment.
3. **The cache is the single source of truth** for the latest price, previous price, session open price and the 5-minute history ring buffer.
4. **The source owns *which* tickers are priced; the app owns *why*.** The app decides the tracked set (watchlist ∪ positions, PLAN §6) and calls `add_ticker`/`remove_ticker`. The source only does what it's told.
5. **Never crash the loop.** Network errors, bad payloads and simulator exceptions are logged, and the next cycle retries.

```
             env: MASSIVE_API_KEY, MASSIVE_POLL_INTERVAL
                              │
                 create_market_data_source(cache)
                   ┌──────────┴───────────┐
       SimulatorDataSource         MassiveDataSource
       (GBM, 500 ms)               (REST poll, 15 s default; LIVE or EOD mode)
                   └──────────┬───────────┘
                              ▼  cache.update(ticker, price)
                         PriceCache  ── latest / previous / open / history / version
              ┌───────────────┼─────────────────┬──────────────────┐
     SSE /api/stream/prices   GET /api/prices/  portfolio &       LLM portfolio
     (version-based push)     {t}/history       trade execution   context
```

---

## 2. Module layout

```
backend/app/market/
├── __init__.py        # public exports (below)
├── models.py          # PriceUpdate, PricePoint
├── cache.py           # PriceCache
├── interface.py       # MarketDataSource (ABC)
├── factory.py         # create_market_data_source()
├── simulator.py       # GBMSimulator + SimulatorDataSource      (see MARKET_SIMULATOR.md)
├── seed_prices.py     # seed prices, GBM params, correlation groups
├── massive_client.py  # MassiveDataSource
└── stream.py          # create_stream_router(): SSE + history endpoints
```

**Public API**, the only names other packages import:

```python
from app.market import (
    PriceUpdate, PricePoint, PriceCache, MarketDataSource,
    create_market_data_source, create_stream_router,
)
```

---

## 3. Data models (`models.py`)

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of one ticker's latest price."""
    ticker: str
    price: float            # rounded to 2 dp
    previous_price: float   # price at the previous update (== price on first update)
    open_price: float       # [change] first price seen this process, a.k.a. session open
    timestamp: float        # Unix seconds (float), wall-clock time the cache received it

    @property
    def change(self) -> float:            # tick-to-tick, used for flash direction only
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:    # tick-to-tick %
        return 0.0 if self.previous_price == 0 else round(
            (self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def session_change_percent(self) -> float:   # the UI's "Chg %" (PLAN §6)
        return 0.0 if self.open_price == 0 else round(
            (self.price - self.open_price) / self.open_price * 100, 4)

    @property
    def direction(self) -> str:           # "up" | "down" | "flat"
        ...

    def to_dict(self) -> dict:
        """Exactly the SSE payload fields of PLAN §6."""
        return {
            "ticker": self.ticker, "price": self.price,
            "previous_price": self.previous_price, "open_price": self.open_price,
            "timestamp": self.timestamp, "change": self.change,
            "change_percent": self.change_percent, "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One point in the history ring buffer."""
    timestamp: float   # Unix seconds
    price: float

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "price": self.price}
```

`session_change_percent` is a convenience for server-side consumers such as the LLM context. It is **not** in the SSE payload, because the frontend computes Chg % from `price` and `open_price`.

---

## 4. `PriceCache` (`cache.py`)

A thread-safe (one `threading.Lock`) in-memory store. Writers are the active source's background task. Readers are request handlers and the SSE generator.

```python
class PriceCache:
    HISTORY_SECONDS = 300          # PLAN §6: last 5 minutes
    HISTORY_MAX_POINTS = 600       # 5 min at 500 ms; hard cap on memory

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a price. Sets open_price on the first update for this ticker,
        carries it forward afterwards, appends to history, bumps version."""

    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None
    def get_all(self) -> dict[str, PriceUpdate]          # shallow copy
    def get_history(self, ticker: str) -> list[PricePoint]   # [change] oldest first, ≤ 5 min old
    def remove(self, ticker: str) -> None                # drops latest, open AND history
    @property
    def version(self) -> int                              # monotonic; bumped on every update
    def __contains__(self, ticker: str) -> bool
    def __len__(self) -> int
```

### Behaviour

| Concern | Rule |
|---|---|
| Session open | `open_price` = price of the **first** `update()` for that ticker since process start, or since the ticker was last `remove()`d. Removing and re-adding a ticker starts a new session for it. `reset` (PLAN §8) doesn't clear the cache, so open prices survive a reset for tickers that stay tracked. |
| History | `collections.deque(maxlen=HISTORY_MAX_POINTS)` per ticker. `update()` appends `PricePoint(ts, price)`. `get_history()` returns points with `ts >= now - HISTORY_SECONDS`. The count cap bounds the simulator, and the age filter bounds slow Massive polling (15 s gives ~20 points). |
| Timestamps | `timestamp` defaults to `time.time()`. Sources should **not** pass exchange timestamps: Massive trade times repeat between polls and EOD bars are hours old, which would break the strictly ascending time axis Lightweight Charts requires. Receipt time keeps history monotonic. |
| Rounding | `price`, `previous_price` and `open_price` are rounded to 2 dp on write. |
| Unknown ticker | `get`/`get_price` return `None`. `get_history` returns `[]`, which is how the history endpoint gives `200` with empty `points` for an untracked ticker. |

### Implementation sketch

```python
def update(self, ticker, price, timestamp=None):
    with self._lock:
        ts = timestamp if timestamp is not None else time.time()
        price = round(price, 2)
        prev = self._prices.get(ticker)
        upd = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=prev.price if prev else price,
            open_price=prev.open_price if prev else price,
            timestamp=ts,
        )
        self._prices[ticker] = upd
        self._history.setdefault(ticker, deque(maxlen=self.HISTORY_MAX_POINTS)).append(
            PricePoint(ts, price))
        self._version += 1
        return upd

def get_history(self, ticker):
    cutoff = time.time() - self.HISTORY_SECONDS
    with self._lock:
        return [p for p in self._history.get(ticker, ()) if p.timestamp >= cutoff]

def remove(self, ticker):
    with self._lock:
        self._prices.pop(ticker, None)
        self._history.pop(ticker, None)
        self._version += 1          # so SSE pushes a frame without the removed ticker
```

(`ts if timestamp is not None` replaces the current `timestamp or time.time()`, which treats `0.0` as missing.)

---

## 5. `MarketDataSource` (`interface.py`)

The existing ABC is unchanged:

```python
class MarketDataSource(ABC):
    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing prices for `tickers`. Call exactly once.
        Should leave the cache populated (simulator: always; Massive: if the first poll succeeds)."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task. Idempotent. No cache writes afterwards."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start pricing `ticker`. No-op if already tracked.
        Simulator: prices immediately. Massive: priced on the next poll."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop pricing `ticker` and remove it from the cache. No-op if unknown."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers."""
```

**Contract notes**

- Tickers arrive already normalized (trimmed, uppercased, validated against `^[A-Z][A-Z0-9.]{0,9}$`) by the app layer. Sources still `.upper().strip()` defensively.
- `add_ticker` and `remove_ticker` are `async` so an implementation *may* do I/O, but neither current one awaits the network inside them. They return immediately.
- `start()` must not raise because of a remote failure (bad key, network down). It logs and keeps running so the app still boots. Only programming errors propagate.

---

## 6. Factory (`factory.py`)

```python
def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        interval = _env_float("MASSIVE_POLL_INTERVAL", default=15.0, minimum=1.0)  # [change]
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)
    return SimulatorDataSource(price_cache=price_cache)


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default
```

| Env var | Effect |
|---|---|
| `MASSIVE_API_KEY` unset or blank | Simulator |
| `MASSIVE_API_KEY` set | Massive |
| `MASSIVE_POLL_INTERVAL` | Seconds between Massive polls. Default `15` (free tier: 5 calls/min). Floor `1`. Bad values fall back to the default with a warning. Ignored by the simulator. |

The factory returns an **unstarted** source.

---

## 7. `MassiveDataSource` (`massive_client.py`)

### 7.1 Modes

The free Basic plan has **no snapshot access** and only end-of-day data (see `MASSIVE_API.md` §1). The source therefore has two modes and picks one on the first poll:

| Mode | When | Call per poll | Covers |
|---|---|---|---|
| `LIVE` | Snapshot call succeeds (Starter+: delayed or real-time) | `get_snapshot_all(STOCKS, tickers)`, one call for all tickers | Every `MASSIVE_POLL_INTERVAL` s |
| `EOD` | Snapshot raises `BadResponse` whose body says not-authorized / not entitled (HTTP 403) | `get_grouped_daily_aggs(date)` for the latest trading day, filtered to tracked tickers | Every `max(MASSIVE_POLL_INTERVAL, 300)` s; the data only changes once a day |

The switch to EOD happens once, with a single `WARNING` log line: "Massive key has no snapshot access (Basic plan?): using end-of-day closes". Other errors (401 bad key, 429, 5xx, network) don't change mode. They're logged and retried next interval. In EOD mode, prices are static, so the UI shows a flat line and Chg % 0. That's honest for an EOD feed.

### 7.2 Price selection (LIVE mode)

Use the first non-empty value of:

```python
snap.last_trade.price        # needs trades entitlement
snap.min.close               # latest minute bar
snap.day.close               # today's bar (zeroed right after the 3:30 AM ET reset)
snap.prev_day.close          # yesterday's close, the overnight fallback
```

Skip a ticker (warn once) if all are missing. Use the real model attribute names: **`last_trade.sip_timestamp` is nanoseconds and there is no `last_trade.timestamp`**. In any case, the cache is stamped with receipt time (§4), so no exchange timestamp is needed.

### 7.3 Sketch

```python
class MassiveDataSource(MarketDataSource):
    EOD_MIN_INTERVAL = 300.0

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0):
        self._api_key, self._cache, self._interval = api_key, price_cache, poll_interval
        self._tickers: list[str] = []
        self._client: RESTClient | None = None
        self._task: asyncio.Task | None = None
        self._mode: Literal["live", "eod"] = "live"
        self._eod: dict[str, float] = {}           # last grouped-daily closes, all tickers
        self._eod_fetched_at: float = 0.0

    async def start(self, tickers):
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = [t.upper().strip() for t in tickers]
        await self._poll_once()                       # populate cache before serving
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")

    async def _poll_loop(self):
        while True:
            await asyncio.sleep(self._interval if self._mode == "live"
                                else max(self._interval, self.EOD_MIN_INTERVAL))
            await self._poll_once()

    async def _poll_once(self):
        if not self._tickers or not self._client:
            return
        try:
            if self._mode == "live":
                prices = await asyncio.to_thread(self._fetch_live, list(self._tickers))
            else:
                prices = await asyncio.to_thread(self._fetch_eod, set(self._tickers))
        except BadResponse as e:
            if self._mode == "live" and _is_not_entitled(e):
                logger.warning("Massive key has no snapshot access (Basic plan?): using end-of-day closes")
                self._mode = "eod"
                return await self._poll_once()
            logger.error("Massive poll failed: %s", e)
            return
        except Exception:
            logger.exception("Massive poll failed")
            return
        for ticker, price in prices.items():
            if ticker in self._tickers:               # ignore tickers removed mid-poll
                self._cache.update(ticker, price)

    def _fetch_live(self, tickers) -> dict[str, float]:
        snaps = self._client.get_snapshot_all(SnapshotMarketType.STOCKS, tickers)
        return {s.ticker: p for s in snaps if (p := _pick_price(s)) is not None}

    def _fetch_eod(self, wanted) -> dict[str, float]:
        if not self._eod or time.time() - self._eod_fetched_at > 6 * 3600:
            self._eod = _latest_grouped_closes(self._client)   # walks back ≤ 7 days
            self._eod_fetched_at = time.time()
        missing = wanted - self._eod.keys()
        # Ticker not in grouped data (rare): fall back to /prev, one call each
        for t in list(missing)[:2]:                   # stay inside 5 calls/min
            if (bars := self._client.get_previous_close_agg(t)):
                self._eod[t] = bars[0].close
        return {t: self._eod[t] for t in wanted if t in self._eod}
```

`add_ticker` appends to `_tickers` (priced on the next poll; PLAN §6 accepts this). `remove_ticker` drops it from `_tickers` and calls `cache.remove()`.

`_is_not_entitled(e)` checks `str(e)` (the response body) for `NOT_AUTHORIZED` or `not entitled`. `BadResponse` carries no status code.

---

## 8. Using the API in the app

### 8.1 Startup and shutdown (`lifespan`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                          # schema + seed (PLAN §7)
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(sorted(db.watchlist_tickers() | db.position_tickers()))
    app.state.price_cache, app.state.market = cache, source

    record_snapshot(cache)                             # PLAN §3 step 3
    snap_task = asyncio.create_task(snapshot_loop(cache, every=30))
    try:
        yield
    finally:
        snap_task.cancel()
        await source.stop()

app.include_router(create_stream_router(cache))       # or build inside lifespan via app.state
```

### 8.2 Tracked tickers = watchlist ∪ positions (PLAN §6)

Keep this logic in one place in the app layer, e.g. `app/services/tracking.py`:

```python
async def on_watchlist_add(source, ticker):
    await source.add_ticker(ticker)

async def on_watchlist_remove(source, ticker):
    if not db.has_position(ticker):
        await source.remove_ticker(ticker)

async def on_position_closed(source, ticker):          # after a sell leaves dust → row deleted
    if not db.on_watchlist(ticker):
        await source.remove_ticker(ticker)

async def resync(source):                              # after POST /api/reset
    wanted = db.watchlist_tickers() | db.position_tickers()
    current = set(source.get_tickers())
    for t in current - wanted: await source.remove_ticker(t)
    for t in wanted - current: await source.add_ticker(t)
```

A buy of an untracked ticker can't happen: the trade rule rejects tickers with no cached price ("Add it to your watchlist first").

### 8.3 Reading prices

```python
price = cache.get_price("AAPL")             # trade execution: None → 400 "No price available…"
upd = cache.get("AAPL")                     # watchlist row: price, open_price (or nulls)
everything = cache.get_all()                # portfolio valuation, LLM context
points = cache.get_history("AAPL")          # GET /api/prices/AAPL/history
```

### 8.4 Endpoints owned by `stream.py`

```python
def create_stream_router(cache: PriceCache) -> APIRouter:
    router = APIRouter(prefix="/api")          # build a NEW router per call (no module global)

    @router.get("/stream/prices")
    async def stream_prices(request: Request):
        # "retry: 1000\n\n", then every 0.5 s: if cache.version changed,
        # "data: {ticker: update.to_dict(), ...}\n\n" for ALL tracked tickers
        ...

    @router.get("/prices/{ticker}/history")
    async def price_history(ticker: str):
        t = ticker.strip().upper()
        return {"ticker": t, "points": [p.to_dict() for p in cache.get_history(t)]}

    return router
```

---

## 9. Changes from the current code

| # | File | Change | Source |
|---|---|---|---|
| 1 | `models.py` | Add `open_price` to `PriceUpdate` and `to_dict()`. Add `session_change_percent`. Add `PricePoint`. | PLAN §6 [change] |
| 2 | `cache.py` | Track open price. Add per-ticker history deque and `get_history()`. `remove()` clears history and bumps version. `timestamp is not None` fix. | PLAN §6 [change] |
| 3 | `factory.py` | Read `MASSIVE_POLL_INTERVAL` (default 15, floor 1). | PLAN §5/§6 [change] |
| 4 | `massive_client.py` | **Bug:** the code reads `snap.last_trade.timestamp`, which doesn't exist on the client's `LastTrade` model (`sip_timestamp`, ns). Against the real API every snapshot raises `AttributeError` and is skipped, so no prices are ever written. Fix: use the §7.2 price fallback and stamp with receipt time. | Research |
| 5 | `massive_client.py` | Add EOD mode (grouped daily) for keys without snapshot access (free Basic plan). | Research |
| 6 | `stream.py` | Router is a module-level global, so calling the factory twice registers routes twice. Create it inside the factory. Add the history endpoint. | Review / PLAN §8 |
| 7 | `tests/market/test_massive.py` | Build fixtures with `TickerSnapshot.from_dict({...})` instead of `MagicMock`, which hid bug #4. Cover fallback order, EOD switch, removed-mid-poll. | Research |
| 8 | `tests/market/` | New tests: open price is set once and survives updates; history age/count limits; `remove` clears history; `MASSIVE_POLL_INTERVAL` parsing. | PLAN §12 |

Nothing else changes for consumers. `SimulatorDataSource` needs no code change: the cache supplies open and history for free.

# Market Simulator: Approach and Code Structure

How FinAlly makes believable, live-looking stock prices with no API key. The simulator is the **default** market data source (used whenever `MASSIVE_API_KEY` is unset) and implements the same `MarketDataSource` interface as the Massive client (see `MARKET_INTERFACE.md`).

Code: `backend/app/market/simulator.py` and `backend/app/market/seed_prices.py`. Tests: `backend/tests/market/test_simulator*.py`.

---

## 1. Goals

| Goal | How |
|---|---|
| Looks like a real market | Geometric Brownian Motion (log-normal, never negative), realistic per-stock volatility |
| Stocks move together | Sector-correlated random shocks (Cholesky) |
| Something to watch | Rare 2–5% "event" jumps, so the flash animations and P&L have drama |
| Streams smoothly | One step every 500 ms, matching the SSE cadence |
| Any ticker works | Unknown symbols get a random seed price and default parameters, priced immediately |
| Zero dependencies | In-process asyncio task plus `numpy`. No network, no files |
| Testable | Pure, synchronous math core (`GBMSimulator`) separate from the async adapter (`SimulatorDataSource`) |

Non-goals: order-book microstructure, bid/ask spreads, market hours, volume, mean reversion, historical replay.

---

## 2. The model

### 2.1 Geometric Brownian Motion

For each ticker, every tick:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt + σ·√Δt·Z )
```

| Symbol | Meaning | Value |
|---|---|---|
| `S` | price | starts at seed price |
| `μ` | annualized drift | 0.03–0.08 per ticker |
| `σ` | annualized volatility | 0.17 (V) … 0.50 (TSLA) |
| `Δt` | tick length as a fraction of a trading year | `0.5 / (252 · 6.5 · 3600)` ≈ **8.48 × 10⁻⁸** |
| `Z` | standard normal, **correlated across tickers** (§2.2) | |

Why GBM: the exponential keeps prices positive, returns are scale-free (a $50 and an $800 stock move by the same %), and `σ` reads directly as the familiar "annual volatility" number. The `−σ²/2` term (Itô correction) makes `μ` the true expected return.

**Scale check.** One-tick σ for AAPL is `0.22 · √8.48e-8 ≈ 0.0064%`, about 1¢ on $190. Over the 5-minute chart window (600 ticks) that is `0.22 · √(300/5,896,800) ≈ 0.16%`, about ±30¢. Moves are realistic and calm, and the chart is livened up by events (§2.3) and by the high-vol names (TSLA, NVDA). If a demo needs more motion, scale `Δt` with a `time_scale` constructor argument (e.g. `time_scale=10` makes 1 real second simulate 10 market seconds). The default stays 1.

### 2.2 Correlated moves (Cholesky)

Real stocks share market and sector factors. We draw `n` independent normals `z` and turn them into correlated ones:

```
C  = correlation matrix (n × n), C[i][i] = 1
L  = cholesky(C)            # C = L · Lᵀ
Z  = L · z                  # Cov(Z) = C
```

Pairwise correlation comes from sector groups in `seed_prices.py`:

| Pair | ρ |
|---|---|
| Both in `tech` {AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX} | 0.6 |
| Both in `finance` {JPM, V} | 0.5 |
| Anything involving TSLA | 0.3 (it does its own thing) |
| Cross-sector or unknown ticker | 0.3 |

`L` is rebuilt (O(n²) to build, O(n³) to factor, which is trivial for n < 50) whenever a ticker is added or removed, **not** on every tick. The hot path is one `n×n @ n` mat-vec.

*Positive definiteness:* every off-diagonal value is in [0.3, 0.6] with one common floor, so `C = 0.3·J + 0.7·I + (block terms)` has a smallest eigenvalue ≥ 0.4. Cholesky can't fail with these constants. If someone edits them, keep intra-group ρ ≥ cross-group ρ, or wrap the call in `try/except LinAlgError` and fall back to independent draws.

### 2.3 Random events

After the GBM step, each ticker has probability `event_probability` (default **0.001**) of a jump:

```
S ← S · (1 ± U(0.02, 0.05))      # sign is a coin flip
```

With 10 tickers at 2 ticks/s that's 20 draws/s, so **about one event every 50 s** somewhere on the board. Events are independent (not correlated) and logged at DEBUG.

### 2.4 Seeds and parameters

`seed_prices.py` holds plain dicts, so new names are a one-line change:

```python
SEED_PRICES   = {"AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "AMZN": 185.0, "TSLA": 250.0,
                 "NVDA": 800.0, "META": 500.0, "JPM": 195.0, "V": 280.0, "NFLX": 600.0}
TICKER_PARAMS = {"AAPL": {"sigma": 0.22, "mu": 0.05}, ..., "TSLA": {"sigma": 0.50, "mu": 0.03}}
DEFAULT_PARAMS = {"sigma": 0.25, "mu": 0.05}           # any other ticker
CORRELATION_GROUPS = {"tech": {...}, "finance": {"JPM", "V"}}
INTRA_TECH_CORR, INTRA_FINANCE_CORR, CROSS_GROUP_CORR, TSLA_CORR = 0.6, 0.5, 0.3, 0.3
```

Unknown tickers (e.g. `PYPL` added from chat) start at `uniform(50, 300)` with `DEFAULT_PARAMS` and cross-group correlation.

**Recommended tweak:** derive the unknown-ticker seed from the symbol, e.g. `random.Random(ticker).uniform(50, 300)`, so `PYPL` starts at the same price after every restart instead of jumping relative to a held position's `avg_cost`. Known tickers already restart at their fixed seed, and the simulator is intentionally memory-less across restarts.

---

## 3. Code structure

```
seed_prices.py         constants only (no logic)
        │
simulator.py
├── GBMSimulator            pure, synchronous, no I/O, no asyncio
│     __init__(tickers, dt=DEFAULT_DT, event_probability=0.001)
│     step() -> dict[str, float]         advance every ticker one tick
│     add_ticker(t) / remove_ticker(t)   update state + rebuild Cholesky
│     get_price(t) -> float | None
│     get_tickers() -> list[str]
│     _add_ticker_internal(t)            seed price + params (no rebuild, for batch init)
│     _rebuild_cholesky()
│     _pairwise_correlation(t1, t2)      static, sector lookup
│
└── SimulatorDataSource(MarketDataSource)   async adapter → PriceCache
      __init__(price_cache, update_interval=0.5, event_probability=0.001)
      start(tickers)    build GBMSimulator, seed cache with initial prices, spawn task
      stop()            cancel task (idempotent)
      add_ticker(t)     sim.add_ticker + write price to cache NOW (PLAN: "priced immediately")
      remove_ticker(t)  sim.remove_ticker + cache.remove
      get_tickers()
      _run_loop()       while True: step → cache.update each → sleep(interval)
```

Splitting the **model** from the **runtime** keeps the math testable without an event loop. Tests call `GBMSimulator.step()` directly and check statistics. The adapter is tested with a real `PriceCache` and short intervals.

### 3.1 The hot path

```python
def step(self) -> dict[str, float]:
    n = len(self._tickers)
    if n == 0:
        return {}
    z = np.random.standard_normal(n)
    if self._cholesky is not None:            # None when n == 1
        z = self._cholesky @ z
    out = {}
    for i, t in enumerate(self._tickers):
        mu, sigma = self._params[t]["mu"], self._params[t]["sigma"]
        self._prices[t] *= math.exp((mu - 0.5 * sigma**2) * self._dt
                                    + sigma * math.sqrt(self._dt) * z[i])
        if random.random() < self._event_prob:
            self._prices[t] *= 1 + random.uniform(0.02, 0.05) * random.choice((-1, 1))
        out[t] = round(self._prices[t], 2)
    return out
```

The simulator keeps **full-precision** internal prices and only rounds what it publishes, so cent rounding never compounds.

### 3.2 The loop

```python
async def _run_loop(self) -> None:
    while True:
        try:
            for ticker, price in self._sim.step().items():
                self._cache.update(ticker=ticker, price=price)
        except Exception:
            logger.exception("Simulator step failed")      # never kill the loop
        await asyncio.sleep(self._interval)
```

- The step runs on the event loop thread. It takes microseconds for tens of tickers, so it needs no `to_thread`.
- `add_ticker`/`remove_ticker` run on the same loop, so they can't interleave with a `step()` mid-way and the simulator needs no lock. The `PriceCache` has its own lock for cross-thread readers.
- Interval drift (sleep plus step time) doesn't matter. SSE pushes on cache version change, not on wall-clock alignment.

### 3.3 What the cache adds

The simulator only calls `cache.update(ticker, price)`. Everything else in PLAN §6 is derived by `PriceCache` (see `MARKET_INTERFACE.md` §4):

- `previous_price` / `direction`: flash colour
- `open_price`: first price this process, used for **Chg %**
- 5-minute history ring buffer (600 points at 500 ms): `GET /api/prices/{ticker}/history`

So the PLAN §6 [change] items need **no simulator changes**.

---

## 4. Lifecycle example

```python
cache = PriceCache()
sim = SimulatorDataSource(cache)                 # usually via create_market_data_source(cache)

await sim.start(["AAPL", "GOOGL", "MSFT"])       # cache has 3 prices immediately
await sim.add_ticker("PYPL")                     # priced immediately (random seed)
await asyncio.sleep(2)                           # ~4 ticks
cache.get("PYPL")                                # PriceUpdate(..., open_price=<seed>)
cache.get_history("AAPL")                        # ~5 PricePoints
await sim.remove_ticker("GOOGL")                 # gone from sim and cache
await sim.stop()
```

---

## 5. Testing approach

| Area | Test |
|---|---|
| GBM correctness | Prices stay > 0 over 10k steps. With `event_probability=0` and a large `dt`, the sample mean and variance of log-returns ≈ `(μ−σ²/2)Δt` and `σ²Δt`. |
| Correlation | With `dt` large and events off, the empirical correlation of log-returns for AAPL/MSFT ≈ 0.6 and JPM/V ≈ 0.5 (±0.05 over ~5k steps). |
| Events | `event_probability=1.0` → every step moves each price by 2–5% beyond GBM noise. `0.0` → never. |
| Dynamic tickers | Add or remove rebuilds Cholesky with the right shape. Adding a duplicate is a no-op. Removing the last ticker leaves `_cholesky is None`. Unknown ticker seed is in [50, 300]. |
| Adapter | `start` seeds the cache. `add_ticker` writes the cache immediately. `remove_ticker` clears it. `stop` is idempotent. The loop survives an injected exception. |
| Determinism | `np.random.seed(…)` + `random.seed(…)` in fixtures. Cleaner: inject one `np.random.Generator` into `GBMSimulator(rng=...)` and use it for both normals and events. |

The existing suite (`test_simulator.py`: 17, `test_simulator_source.py`: 10) covers most of this. Add the statistical moment and correlation checks if they aren't there yet.

---

## 6. Tuning knobs

| Knob | Where | Default | Effect |
|---|---|---|---|
| `update_interval` | `SimulatorDataSource` | 0.5 s | Tick rate. Keep in step with SSE's 0.5 s and the 600-point history cap. |
| `event_probability` | both classes | 0.001 | Drama frequency (per ticker per tick) |
| `dt` / `time_scale` | `GBMSimulator` | 0.5 s of a trading year | Overall volatility per tick |
| `TICKER_PARAMS` | `seed_prices.py` | per ticker | Per-name volatility and drift |
| Correlation constants | `seed_prices.py` | 0.6 / 0.5 / 0.3 | Co-movement |

There's no env var for these. They're code-level constants, so behaviour is identical for every student and every E2E run.

---

## 7. Demo

```bash
cd backend
uv run market_data_demo.py     # Rich terminal dashboard: 10 tickers, sparklines, event log, 60 s
```

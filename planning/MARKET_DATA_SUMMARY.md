# Market Data Backend — Summary

**Status:** Complete and tested. All findings in `MARKET_DATA_REVIEW.md` are resolved (see "Review Fixes" below). The simulator path is verified end to end over HTTP. The Massive path is verified against the real `massive` model classes but has not been run against the live API (no key configured).

## What Was Built

A market data subsystem in `backend/app/market/` (9 modules) providing live price simulation and real market data via a unified interface.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Massive (Polygon.io) REST poller (when MASSIVE_API_KEY set)
        │                     live snapshots, or end-of-day closes on free keys
        ▼
   PriceCache (thread-safe, in-memory: latest, session open, 5-min history, version)
        │
        ├──→ SSE stream endpoint     GET /api/stream/prices
        ├──→ History endpoint        GET /api/prices/{ticker}/history
        ├──→ Portfolio valuation
        └──→ Trade execution
```

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PriceUpdate` (ticker, price, previous_price, open_price, timestamp; change, change_percent, session_change_percent, direction) and `PricePoint` |
| `interface.py` | `MarketDataSource` — abstract base class: `start/stop/add_ticker/remove_ticker/get_tickers` |
| `cache.py` | `PriceCache` — latest price, session open, per-ticker history (≤ 600 points, ≤ 5 min), strictly increasing timestamps, version counter |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params, correlation groups |
| `simulator.py` | `GBMSimulator` (GBM with Cholesky-correlated moves, random events, deterministic seeds for unknown tickers) + `SimulatorDataSource` |
| `massive_client.py` | `MassiveDataSource` — LIVE snapshot polling with a price fallback chain; switches once to EOD (grouped-daily closes) when the key lacks snapshot access |
| `factory.py` | `create_market_data_source()` — simulator or Massive from `MASSIVE_API_KEY`; reads `MASSIVE_POLL_INTERVAL` (default 15, min 1) |
| `stream.py` | `create_stream_router()` — SSE stream (version-based change detection, keep-alive) and history endpoint |

### Key Design Decisions

- **Strategy pattern** — both sources implement the same ABC; downstream code is source-agnostic
- **PriceCache as single point of truth** — producers write, consumers read
- **Receipt-time timestamps** — both sources stamp prices when the cache receives them, forced strictly increasing per ticker, so chart data is always ascending
- **Session open** — the first price seen per ticker since process start (or since the ticker was last removed); the UI's "Chg %" is measured from it
- **GBM with correlated moves** — tech 0.6, finance 0.5, cross-sector and TSLA 0.3
- **Random shock events** — ~0.1% chance per tick per ticker of a 2–5% move

## Test Suite

**139 tests, all passing. Coverage 99%.** 8 test modules in `backend/tests/market/`.

| Module | Covers |
|--------|--------|
| test_models.py | `PriceUpdate`/`PricePoint` fields, derived values, SSE key order |
| test_cache.py | Prices, session open, history count/age limits, monotonic timestamps, version on remove |
| test_simulator.py | GBM maths, deterministic unknown seeds, Cholesky with many tickers |
| test_simulator_source.py | Async lifecycle, normalization, immediate pricing, no duplicate history |
| test_factory.py | Source selection, `MASSIVE_POLL_INTERVAL` parsing (invalid, NaN, inf, clamping) |
| test_massive.py | Real-model fixtures: price fallback, LIVE→EOD switch, weekend walk-back, `/prev` cap, removal-mid-poll guard |
| test_stream.py | SSE frames, change detection, removal frames, keep-alive, cancellation, history endpoint |

## Review Fixes

`MARKET_DATA_REVIEW.md` (2026-10-13) found 15 issues. All are fixed:

| # | Fix |
|---|-----|
| C1 | Massive client rewritten: no more `last_trade.timestamp`; `pick_price()` fallback chain; receipt-time stamps |
| H1 | Free keys: one WARNING, then end-of-day closes (hourly refresh, weekend walk-back, ≤ 2 `/prev` calls per poll) |
| H2 | Prices for tickers removed during an in-flight poll are discarded; the worker thread gets a copy of the ticker list |
| M1 | Unknown tickers get a deterministic seed price derived from the symbol |
| M2 | Cache forces strictly increasing timestamps per ticker; `timestamp=0.0` is respected |
| M3 | `remove()` bumps the version, so SSE pushes a frame without the ticker |
| M4 | New `test_stream.py`; `stream.py` coverage 49% → 98% |
| M5 | `get_history()` returns only the last 5 minutes (≤ 600 points) |
| L1 | `MASSIVE_POLL_INTERVAL`: NaN/inf → default, values below 1 s clamped to 1 s |
| L2 | SSE generator no longer swallows `CancelledError` |
| L3 | Both sources normalize tickers (strip + uppercase) |
| L4 | SSE sends `: keep-alive` after 15 s of silence |
| L5 | `backend/CLAUDE.md`, `backend/README.md`, this summary and `interface.py` docs updated |
| L6 | `ruff format` applied; format check added to the documented commands |
| L7 | `open_price` is a required field; `PricePoint` exported; `version` read under the lock; `rich` moved to the dev extra |

## Demo

A Rich terminal demo is available at `backend/market_data_demo.py`:

```bash
cd backend
uv run --extra dev market_data_demo.py
```

## Usage for Downstream Code

```python
from app.market import PriceCache, create_market_data_source, create_stream_router

# Startup (FastAPI lifespan)
cache = PriceCache()
source = create_market_data_source(cache)  # Reads MASSIVE_API_KEY / MASSIVE_POLL_INTERVAL
await source.start(sorted(watchlist_tickers | held_tickers))
app.include_router(create_stream_router(cache))

# Read prices
update = cache.get("AAPL")          # PriceUpdate or None
price = cache.get_price("AAPL")     # float or None
chg = update.session_change_percent # the UI's "Chg %"
points = cache.get_history("AAPL")  # list[PricePoint], last ~5 min

# Dynamic tracking (watchlist ∪ positions)
await source.add_ticker("PYPL")     # simulator: priced immediately; Massive: next poll
await source.remove_ticker("GOOGL") # only when no position is held

# Shutdown
await source.stop()
```

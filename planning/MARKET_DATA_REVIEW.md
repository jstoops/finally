# Market Data Backend — Code Review

**Date:** 2026-10-13
**Scope:** `backend/app/market/` (9 modules, 380 statements) and `backend/tests/market/` (7 modules, 93 tests), at `main` @ `484aa85`
**Reviewed against:** `PLAN.md` §6/§8/§12, `MARKET_DATA_DESIGN.md` (§13 change checklist, §14 edge cases), `MARKET_INTERFACE.md`, `MASSIVE_API.md`, `MARKET_DATA_SUMMARY.md`

> **Resolution (2026-10-13):** all findings below are fixed on branch `fix/market-data-review`. See the "Review Fixes" table in `MARKET_DATA_SUMMARY.md`.

## Verdict

**The simulator path is ready to build on. The Massive path is not usable and needs the planned rewrite.**

- The simulator, price cache, SSE stream and history endpoint meet PLAN §6 and §8. The code is small, readable and well separated, and the default (simulator) experience will work as specified.
- **With a Massive API key, no price is ever cached.** The client reads `last_trade.timestamp`, a field that doesn't exist on the real model. Every snapshot is skipped, so the watchlist shows nothing and every trade is rejected. The unit tests pass only because they use `MagicMock` fixtures.
- `MARKET_DATA_DESIGN.md` already found this bug and specifies a rewrite (§8, checklist items 7–8). PR #5 implemented the PLAN `[change]` items, but only part of the design checklist. The rest of this review lists what is still outstanding.
- `MARKET_DATA_SUMMARY.md` says "Status: Complete, tested, reviewed, all issues resolved" and "73 tests". Both are out of date and the first is misleading.

| Severity | Count | Items |
|---|---|---|
| Critical | 1 | C1 |
| High | 2 | H1, H2 |
| Medium | 5 | M1–M5 |
| Low | 7 | L1–L7 |

Tests: 93 pass, `ruff check` is clean, coverage is 93% overall. `stream.py` is at 49% (the SSE generator is untested), and `ruff format --check` would reformat 4 test files.

---

## Critical

### C1. Massive mode never writes a price — `massive_client.py:103`

```python
timestamp = snap.last_trade.timestamp / 1000.0
```

`massive.rest.models.LastTrade` has no `timestamp` attribute. The field is `sip_timestamp`, in **nanoseconds** (see `MASSIVE_API.md` line 119). Every snapshot raises `AttributeError`, which the `except (AttributeError, TypeError)` at line 110 catches, logs as a warning and skips.

I reproduced this with the real model class:

```
>>> snap = TickerSnapshot.from_dict({"ticker": "AAPL", "lastTrade": {"p": 190.5, "t": 1760000000123456789}})
WARNING Skipping snapshot for AAPL: 'LastTrade' object has no attribute 'timestamp'
cached price: None
```

**Impact:** setting `MASSIVE_API_KEY` leaves the cache permanently empty. The SSE stream sends nothing, `GET /api/watchlist` will show `null` prices, every trade is rejected with "No price available", and portfolio valuation falls back to `avg_cost`. All failures are warnings, so nothing points at the cause.

**Why the tests missed it:** `test_massive.py:11` builds snapshots with `MagicMock`, which returns a value for any attribute, including ones that don't exist.

**Fix:** carry out `MARKET_DATA_DESIGN.md` §8.3:

- Stamp cache entries with receipt time (`time.time()`, i.e. call `cache.update()` without `timestamp`), not the exchange time. Exchange times repeat between polls when there's no new trade. That would put duplicate timestamps in the history buffer, and Lightweight Charts rejects data that isn't strictly ascending (see M2).
- Pick the price with the `pick_price()` fallback chain: `last_trade.price` → `min.close` → `day.close` → `prev_day.close`, skipping `None` and `0`. Without this, `last_trade` is `None` on plans without trades entitlement, and `day` is zeroed overnight.
- Rewrite the fixtures with `TickerSnapshot.from_dict({...})` (design §12.5), so a missing attribute fails the test.

---

## High

### H1. Free Massive keys aren't supported — `massive_client.py:123-128`

The free Basic plan has no snapshot entitlement, so `get_snapshot_all` returns `NOT_AUTHORIZED` on every poll. The error is logged at ERROR every 15 s, and the cache stays empty forever. PLAN §6 sets the default poll interval of 15 s specifically to suit the free tier, so the free tier is an intended use.

**Fix:** design §8.1 — on the first `NOT_AUTHORIZED`, switch once to EOD mode, using `get_grouped_daily_aggs` (latest trading day, refreshed hourly). Prices are then yesterday's closes. This is flat but honest, and trades work.

### H2. A ticker removed during a Massive poll comes back as a stale entry — `massive_client.py:97-108`

`_poll_once` awaits `asyncio.to_thread(self._fetch_snapshots)`. If `remove_ticker` runs during that await, it clears the cache. The poll then returns and writes the removed ticker back. Nothing polls that ticker again, so its entry stays in the cache and in every SSE frame, frozen, until restart.

Reproduced with a slow fake fetch:

```
TSLA after remove during poll: 1.0   tracked: ['AAPL']
```

The window is the whole HTTP round trip, which can be several seconds with the client's default 10 s timeout and 3 retries. A user removing a ticker in the UI, or the LLM's watchlist changes, can easily hit it. The app layer will rely on removal to stop pricing unwatched tickers (PLAN §6 "Tracked Tickers").

**Fix:** after the thread returns, re-read `self._tickers` and skip snapshots for tickers no longer tracked (design §14 "Removal race"). Also pass a copy of the list into the thread (`tickers = list(self._tickers)`), so the worker thread never reads a list that `add_ticker` is appending to.

---

## Medium

### M1. Unknown tickers get a new random price on every restart — `simulator.py:151`

```python
self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
```

Positions are persisted in SQLite, but simulated prices are not. A user who buys PYPL at a simulated $120 can restart and see it priced at $280 or $55, a large fake profit or loss with no market cause. It also happens within one session if the ticker is removed and re-added.

**Fix:** design §7's `_unknown_seed_price(ticker)`, which derives a stable price in [50, 300] from a hash of the symbol. Use `hashlib`, not `hash()`, because `hash()` is salted per process. Known tickers already restart at their fixed seeds; that's expected and documented in design §14.

### M2. History timestamps aren't guaranteed to increase — `cache.py:35,50`

The cache appends whatever timestamp it's given. Lightweight Charts throws if `setData` or `update` receives a time that is equal to or earlier than the previous one. This can happen:

- in Massive mode once C1 is fixed with exchange timestamps (the same `sip_timestamp` repeats between polls when there's no new trade);
- when the wall clock steps backwards (NTP adjustment);
- when two `update()` calls land within the clock's resolution. On Windows, `time.time()` has ~15 ms resolution, and `SimulatorDataSource.add_ticker` writes immediately before or after a loop tick.

There's also `ts = timestamp or time.time()`, which treats an explicit `0.0` as "missing".

**Fix:** design §4.1 — per ticker, force each timestamp to be strictly greater than the last (+1 ms), and use `timestamp if timestamp is not None else time.time()`. The frontend can also de-duplicate, but the cache is the single place that fixes it for both the REST history and the SSE stream.

### M3. `remove()` doesn't bump `version` — `cache.py:74-79`

The SSE stream only sends a frame when `version` changes. After a removal, the removed ticker keeps appearing in the client's last frame until the next `update()`. In simulator mode that is ≤ 0.5 s, which nobody will notice. In Massive mode it is up to `MASSIVE_POLL_INTERVAL` (15 s by default): a ticker the user just removed stays on screen, still "live".

**Fix:** increment `_version` in `remove()` (design §4.1). The frontend will drop tickers that aren't in a frame, provided it treats each frame as the complete set.

### M4. The SSE generator has no tests — `stream.py:58-94` (49% coverage)

The plan's central real-time path is untested: the `retry: 1000` preamble, the frame format, sending only on version change, and stopping on disconnect. Design checklist item 10 (`tests/market/test_stream.py`) wasn't implemented, although `httpx` is now a dev dependency, so the test client is available. Call `_generate_events` directly with a fake `Request` whose `is_disconnected()` returns `False` and then `True`, and assert on the yielded strings. That needs no real HTTP connection.

### M5. Massive history covers ~2.5 hours, not ~5 minutes — `cache.py:11`

`HISTORY_SIZE = 600` is sized for the simulator's 500 ms tick. At a 15 s Massive poll, 600 points is 2.5 hours. The main chart then opens with hours of mostly flat data, while PLAN §6 and the endpoint description promise ~5 minutes. It's not a correctness bug, but the chart will look very different between modes.

**Fix:** design §4.1 — keep the count cap and also drop points older than 300 s in `get_history()`.

---

## Low

### L1. A NaN or infinite `MASSIVE_POLL_INTERVAL` stops polling without any message — `factory.py:19-31`

`float("nan")` passes the `<= 0` check. `asyncio.sleep(nan)` raises `ValueError` ("Invalid delay: NaN"). That kills `_poll_loop`, and the task's exception is never retrieved, so prices freeze with only a "Task exception was never retrieved" message at garbage collection. `inf` sleeps forever. A value like `0.1` is accepted and will hit the rate limit at once. **Fix:** use `math.isfinite(value)`, and set a floor of 1 s (design §9).

### L2. `_generate_events` swallows `CancelledError` — `stream.py:93-94`

When Starlette cancels the response task on disconnect, the generator logs and returns normally instead of re-raising. Since Python 3.11 this interferes with structured cancellation (`asyncio.TaskGroup` and `Task.uncancel`). It works with the current Starlette, but can cause hangs at shutdown later. **Fix:** log, then `raise`.

### L3. Ticker normalization differs between the two sources

`MassiveDataSource.add_ticker/remove_ticker` apply `.upper().strip()`. `SimulatorDataSource` and `GBMSimulator` don't, and `start()` doesn't normalize in either source. `add_ticker("aapl")` in simulator mode creates a separate `aapl` series. The app layer will validate tickers (PLAN §7), so this is defensive only, but design §5 asks both sources to normalize. Making them consistent is a one-line change in each method.

### L4. A keep-alive is missing when nothing changes — `stream.py:76-92`

The stream sends nothing while `version` is unchanged: an empty startup watchlist, a stalled Massive feed, or a free key before H1 is fixed. Some proxies and load balancers close idle connections after 30–60 s (relevant to the App Runner and Render targets in PLAN §11). EventSource reconnects, but the status dot will flicker yellow. **Fix:** send a `: keep-alive\n\n` comment roughly every 15 s of silence (design §10).

### L5. Stale and inaccurate docs

- `MARKET_DATA_SUMMARY.md`: still says 73 tests and "all issues resolved", omits `open_price`, the history buffer and endpoint, and `MASSIVE_POLL_INTERVAL`, and lists `massive_client.py` coverage as 56% (it is now 94%, with mocks that hide C1).
- `backend/CLAUDE.md`: the `PriceUpdate` description omits `open_price`, and the SSE section omits `GET /api/prices/{ticker}/history`.
- `interface.py:52`: says `remove_ticker` "also removes the ticker from the PriceCache". True, but the app must only call it when no position is held (PLAN §6), and that rule isn't mentioned anywhere in the subsystem's docs.

### L6. Formatting drift

`ruff format --check` would reformat 4 test files (including `test_simulator.py` and `test_simulator_source.py`), and `stream.py:16` is missing the second blank line before `def`. Run `ruff format app tests` once, and add `ruff format --check` next to `ruff check` in `backend/CLAUDE.md`.

### L7. Minor design notes (no action required)

- `PriceUpdate.open_price` is optional, with a fallback to `price` in `to_dict()`. The cache always sets it, so the fallback only matters for hand-built objects. Design §3 makes it required, which removes a branch. Optional cleanup.
- `rich` is a runtime dependency only because of `market_data_demo.py`, so it ships in the production image. It could move to the `dev` extra.
- `PriceCache.version` is read without the lock. That is safe in CPython (an int read is atomic), but design §4.1 reads it under the lock for consistency.
- `SimulatorDataSource.add_ticker` for an already-tracked ticker writes its current price again, adding a duplicate history point. That's harmless unless M2 is left unfixed.

---

## Conformance with PLAN.md

| Requirement | Status | Notes |
|---|---|---|
| §6 Simulator: GBM, ~500 ms, correlated, random events, realistic seeds | ✅ | Cholesky decomposition verified positive definite with 66 mixed tickers |
| §6 New ticker priced immediately (simulator) | ✅ | `SimulatorDataSource.add_ticker` seeds the cache |
| §6 Unknown tickers start between $50 and $300 | ✅ | Random each time (M1) |
| §6 Massive: REST polling every `MASSIVE_POLL_INTERVAL` s | ❌ | Polls, but caches nothing (C1); free tier unsupported (H1) |
| §6 Cache: latest, previous, timestamp, session open | ✅ | |
| §6 History ring buffer, last 5 min | ⚠️ | 600 points; correct for the simulator, ~2.5 h for Massive (M5); timestamps not strictly increasing (M2) |
| §6 SSE: `retry: 1000`, one event with all tickers, only on change | ✅ | Removal doesn't trigger a frame (M3); no keep-alive (L4) |
| §6 SSE payload fields incl. `open_price` | ✅ | |
| §8 `GET /api/prices/{ticker}/history`, 200 with empty `points` | ✅ | Normalizes case |
| §5 `MASSIVE_POLL_INTERVAL` default 15 | ✅ | Doesn't reject NaN or infinity (L1) |
| §12 Tests for the `[change]` items | ✅ | `test_plan_changes.py` (20 tests) |

## Status of the `MARKET_DATA_DESIGN.md` §13 checklist

| # | Item | Status |
|---|---|---|
| 1–2 | Models: `open_price`, `session_change_percent`, `PricePoint` | Partial: `open_price` added (optional); others not |
| 3–4 | Cache: open price, history, monotonic timestamps, `remove()` bumps version, clock injection | Partial: open price and history done; M2, M3 not |
| 5 | Simulator: deterministic unknown seed, normalization | Not done (M1, L3) |
| 6 | Factory: `MASSIVE_POLL_INTERVAL` with a floor of 1 | Partial: no floor or finiteness check (L1) |
| 7–8 | Massive rewrite and real-model tests | **Not done (C1, H1, H2)** |
| 9 | Stream: router in factory, history endpoint, keep-alive | Partial: keep-alive missing (L4) |
| 10 | `test_stream.py` and `httpx` | Partial: `httpx` added (PR #6); tests not written (M4) |
| 11 | Export `PricePoint` | Not done (depends on 1) |
| 12 | Update `CLAUDE.md` and the summary | Partial (L5) |

---

## What's done well

- **Clear separation.** Sources write, everything else reads the cache. The `MarketDataSource` interface is small, and the strategy pattern keeps SSE and the future portfolio code independent of the source.
- **The simulator is solid.** Full-precision internal prices with rounding only on output (no compounding drift), a correctly derived GBM step, Cholesky-correlated draws rebuilt on add and remove, and a step loop that survives exceptions.
- **No cross-thread access to the cache in simulator mode.** Ticker add, remove and step all run on the event loop without awaiting, so they can't interleave (design §5). The lock covers the Massive worker thread.
- **The `[change]` items are cleanly done.** The session open price, ring buffer, poll-interval parsing and history endpoint are small, tested and match the spec. `test_router_can_be_created_twice` guards against a subtle route-accumulation bug.
- **Good failure posture.** Massive and simulator errors are logged and retried, not raised, so a data-source problem never takes the app down.

## Recommended order of work

1. **C1, H1, H2 together.** Rewrite `massive_client.py` per design §8.3, and rewrite `test_massive.py` with real model fixtures. This is the only blocker, and only for users with a Massive key.
2. **M2, M3 and M5** in `cache.py`: monotonic timestamps, version bump on remove, age-filtered history. These are small and best done before the frontend chart code depends on the current behaviour.
3. **M4:** add `test_stream.py`.
4. **M1 and L1–L4:** a deterministic seed, interval validation, re-raising cancellation, ticker normalization and a keep-alive. Each is a few lines.
5. **L5 and L6:** bring `MARKET_DATA_SUMMARY.md` and `backend/CLAUDE.md` up to date, and run `ruff format`.

Items 1–3 should land before the frontend's main chart and watchlist work starts. Item 1 can wait if the course demo only uses the simulator.

# PLAN.md Review

Reviewed: `planning/PLAN.md` at commit `7766018` (after the `52d26ce` revision), cross-checked against `backend/app/market/`, `backend/pyproject.toml` and the repo layout. Settled decisions from the previous review are not re-raised.

Severity: **High** = agents will build something broken or incompatible. **Medium** = likely bug or rework. **Low** = polish or clarity.

---

## High

### H1. Seeding re-inserts watchlist tickers the user removed (§7)
`INSERT OR IGNORE` of the 10 default tickers runs on every startup. The watchlist rows are keyed by random UUID with `UNIQUE(user_id, ticker)`, so after a user removes `NFLX`, the next restart puts it back. Removals don't survive a restart.

**Fix:** Seed the watchlist only when the `users_profile` row is created. Run `INSERT OR IGNORE INTO users_profile ...`, and if `cursor.rowcount == 1`, insert the default watchlist. This stays idempotent and needs no separate "is the DB empty?" check. Put the same `seed_default_watchlist()` helper behind `/api/reset`.

### H2. Chat history duplicates the new user message (§9 steps 1–4)
Step 1 stores the user message. Step 3 then loads the last 20 messages, which now include that message, and step 4 appends "the user's new message" again. The LLM sees the message twice.

**Fix:** In step 3, load the history *before* storing the message, or exclude the new message by id. Say which one. (State that the 20 messages are the 20 before the new one.)

### H3. Duplicate or non-ascending timestamps will crash Lightweight Charts (§7, §8, §10)
Lightweight Charts needs strictly ascending, unique `time` values and throws on duplicates.
- `recorded_at` is ISO with second precision (`2026-10-09T14:03:22Z`). An LLM response with 2+ trades, or a trade in the same second as the 30s tick, writes two snapshots with the same second.
- The price history and SSE use float seconds at 500ms spacing. Two points then share an integer second.
- In Massive mode, SSE resends a ticker whose `timestamp` hasn't changed whenever any other ticker updates. Appending blindly creates a duplicate.

**Fix:** (a) Store `recorded_at` with milliseconds (`2026-10-09T14:03:22.123Z`) and say so in §7 Conventions. (b) Add to §10 Technical Notes: "Before passing data to Lightweight Charts, convert to seconds, sort ascending, and dedupe by time, keeping the last value. Append an SSE point only if its timestamp is greater than the last plotted point." Also confirm the frontend agent checks whether fractional `UTCTimestamp` values are accepted. If not, floor to integer seconds and keep the last value per second.

### H4. Concurrency model for trades isn't specified (§3, §7)
FastAPI runs `def` endpoints in a threadpool. Stdlib `sqlite3` connections can't be shared across threads by default. Two concurrent buys (e.g. a manual trade while a chat request runs its trades) can both pass the cash check under SQLite's default deferred transactions. The watchlist-remove "only if no position is held" check can race with a buy in the same way.

**Fix:** Add a short "Concurrency" note to §7:
- Use one connection per request/operation (`sqlite3.connect(DB_PATH)`, WAL mode, `busy_timeout=5000`), or one shared connection used only from the event loop.
- Run all portfolio/watchlist mutations under a single process-wide `asyncio.Lock`. The lock covers the cash check, the writes and the matching `market_source.add_ticker/remove_ticker` call. Use `BEGIN IMMEDIATE` for the transaction.
- Route handlers that call `market_source` must be `async def`, because the source methods are async.

### H5. The LLM call must not block the event loop (§9)
The SSE generator, the simulator loop and the snapshot task all run on the event loop. A synchronous `litellm.completion()` inside an `async def` handler freezes price streaming for the 1–3s call, and longer on a timeout.

**Fix:** In §9 step 5, require `await litellm.acompletion(...)` (or `asyncio.to_thread`), with an explicit timeout such as 30s. A timeout returns `502`.

### H6. Percent vs. fraction is ambiguous (§6, §8)
`unrealized_pnl_percent: 0.0105` in the example is a percent (0.20 / 1905 × 100), and `change_percent` is also a percent. `weight: 1.0` is a fraction. A frontend agent seeing `0.0105` next to `weight: 1.0` will likely multiply by 100.

**Fix:** Add one line under the `/api/portfolio` example: "`*_percent` fields are percentages (1.5 = 1.5%); `weight` is a fraction in [0, 1]." Also give the client-side Chg % formula the same units.

### H7. Structured-output schema has optional fields, which strict JSON-schema mode rejects (§9)
`trades` and `watchlist_changes` are marked optional. OpenAI-style strict `json_schema` (which the cerebras skill uses) requires every property to be in `required`, with `additionalProperties: false`. Depending on the provider, an optional field causes a request error or gets silently ignored.

**Fix:** Make both arrays required, and let them be empty. Define the schema as Pydantic models (`side: Literal["buy","sell"]`, `action: Literal["add","remove"]`, `quantity: float`). Then say: "`actions` in the stored message is `null` iff both arrays are empty; otherwise both keys are present (possibly `[]`)." This also settles the current ambiguity about whether a missing key means `[]`.

---

## Medium

### M1. Session open and history after a ticker is removed and re-added (§6 [change])
The existing `remove_ticker` in both sources calls `cache.remove(ticker)`. If the open price and the ring buffer are stored in the cache, they are dropped too. That contradicts "first price recorded since the process started". The simulator also restarts a re-added unknown ticker at a *new* random price.

**Fix:** State the intended behavior: "Removing a ticker from tracking clears its open price and history; re-adding starts a new session for that ticker." This matches the code and is the simplest option. `PriceUpdate` is frozen, so put `open_price` either in `PriceUpdate` (set by `cache.update` from the existing entry) or in a parallel dict. Also say that `/api/reset` clears it for removed tickers.

### M2. Ring buffer is sized by count, not time; Massive timestamps need checking (§6)
"600 points at 500ms" only holds for the simulator. Massive yields about 20 points in 5 minutes. Also, `massive_client.py` divides `last_trade.timestamp` by 1000, assuming milliseconds. Polygon's raw v2 snapshot `lastTrade.t` is **nanoseconds**, so verify what the `massive` SDK returns. If the timestamps are wrong or stale (after hours, every poll carries the same trade time), the history and SSE timestamps are wrong or repeat.

**Fix:** Spec the buffer as `deque(maxlen=600)` and prune points older than 300s *by receive time*. Have the cache record `time.time()` for history and SSE `timestamp`, and keep the trade time only if needed. Add a test that runs against a real Massive response shape.

### M3. Error body shape: FastAPI defaults to `{"detail": ...}` (§8)
`HTTPException` and 422 validation errors return `{"detail": ...}`, but §8 promises `{"error": ...}` for 400/404/503/502. If this isn't called out, the backend agent will use `HTTPException(400, "...")` and the frontend will read `.error` and get `undefined`.

**Fix:** "Register an exception handler that renders `HTTPException` as `{"error": detail}`. 422 keeps FastAPI's `{"detail": [...]}`; the frontend shows a generic message for 422."

### M4. Trade edge cases are under-specified (§7 Trade Rules)
- **Order of rounding vs. validation:** Rounding `0.00001` to 4 dp gives `0`. Say "round to 4 dp, *then* require > 0".
- **Sell within tolerance:** If `quantity` exceeds held by ≤1e-6, sell exactly the held quantity (clamp) so the position goes to zero.
- **Cash drift:** Floats accumulate (e.g. `9999.999999998`). Round `cash_balance` to 2 dp after each trade. The buy check uses `round(qty * price, 2) <= cash + 1e-9`.
- **Sell with no position:** Give the exact message ("You don't hold any {ticker}").
- **Error message templates:** §9 shows "insufficient cash (need $12,450.00, have $8,095.00)". List the canonical 400 messages once in §7 so manual trades and LLM failure notes use the same text and tests can assert on it.

### M5. P&L chart only updates when something forces a refetch (§10 Data Flow)
History is fetched on load, after chat actions and after reset, but not after a manual trade or on the 30s timer. The "P&L chart tracking total portfolio value over time" stays static during a demo.

**Fix:** Pick one: (a) re-fetch `/api/portfolio/history` every 30s and after each manual trade, or (b) append the client-computed live total to the chart every N seconds without persisting it. (a) is simpler and consistent with the server. Also say this is the one allowed poll.

### M6. Local development workflow is undefined (§4, §10, §11)
`output: 'export'` doesn't support Next `rewrites`, so `next dev` on :3000 can't proxy `/api` to :8000 cleanly, and SSE through a dev proxy often buffers. "All API calls go to the same origin" then breaks in dev, and agents will each improvise (CORS, env base URL, etc.).

**Fix:** Specify one approach. For example, a `NEXT_PUBLIC_API_BASE` (empty in production, `http://localhost:8000` in dev) plus CORS for `http://localhost:3000` enabled only when an env flag such as `DEV_CORS=true` is set. Or say "dev = `npm run build` then run FastAPI".

### M7. Static serving and the SPA fallback (§3, §11)
The plan doesn't say where FastAPI finds the export, or what unknown `/api/*` paths return. `StaticFiles(html=True)` mounted at `/` before or around the routers can also shadow routes or return `index.html` for API 404s.

**Fix:** "Static files are served from `STATIC_DIR` (default `backend/static`; the Dockerfile copies `frontend/out` there). Mount it *after* all `/api` routers. Unknown `/api/*` returns JSON 404. If `STATIC_DIR` is missing (local dev), skip the mount."

### M8. Mock LLM matching is loose (§9)
- "contains `buy`" matches "should I buy?" and "buyer". That's fine for tests, but say it is a substring match on purpose.
- `add <TICKER>` has no grammar. Does "address" match? Is the ticker case-normalized? What about "add pypl please"?

**Fix:** Give regexes: `\bbuy\b`, `\bsell\b`, `\badd\s+([A-Za-z][A-Za-z0-9.]{0,9})\b`, `\bremove\s+([A-Za-z][A-Za-z0-9.]{0,9})\b`, with the captured ticker uppercased.

### M9. Watchlist action outcomes in chat aren't defined (§8, §9)
What is the result of the LLM adding a ticker already on the list, or removing one that isn't there? REST treats a duplicate add as success (200) and a missing remove as 404.

**Fix:** "Duplicate add → `executed` (idempotent). Remove of an absent ticker → `failed`, error `"{T} is not on your watchlist"`. Malformed ticker → `failed`." Also define the watchlist failure-note templates the way the trade one is defined.

### M10. Flash animation would trigger on every SSE event in Massive mode (§6, §10)
SSE sends *all* tickers whenever *any* ticker's version changes. A ticker that didn't update keeps its old `direction`. A frontend keyed on `direction` re-flashes stale tickers.

**Fix:** In §10: "Flash only when the ticker's `timestamp` (or `price`) differs from the last value rendered; take the color from comparing against that last rendered price."

### M11. E2E determinism (§12)
- **Heatmap color assertion:** Right after a buy, P&L is ≈0 and its sign is random. Define a neutral band (e.g. |pnl%| < 0.01 → gray) and assert on structure, not on green/red.
- **Isolation:** Tests share one DB and one simulator, so require Playwright `workers: 1`. `docker-compose.test.yml` must use its own volume (or tmpfs) and never `finally-data`.
- **Readiness:** Have the Playwright container wait on `/api/health` (compose `healthcheck` + `depends_on: condition: service_healthy`). `python:3.12-slim` has no `curl`, so use `python -c "import urllib.request..."`.

### M12. Missing project scaffolding the plan assumes
The repo currently has no `db/.gitkeep`, no `.env.example`, and no `.gitignore` entries for `db/finally.db`, `frontend/node_modules`, `frontend/.next` or `frontend/out`. `backend/pyproject.toml` lacks `litellm`, `python-dotenv` and `pydantic` (explicitly), carries `rich` (demo-only) as a runtime dependency, and puts dev tools in an `[project.optional-dependencies] dev` extra, so a plain `uv sync` won't install pytest.

**Fix:** Add a §4/§11 checklist: create `db/.gitkeep` and `.env.example`, add the gitignore entries, add the runtime deps, move dev tools to `[dependency-groups] dev` (which `uv sync` installs locally by default), and use `uv sync --frozen --no-dev` in the Dockerfile.

---

## Low

- **L1. Ticker normalization in path params (§8):** Say that `DELETE /api/watchlist/{ticker}` and `GET /api/prices/{ticker}/history` uppercase and trim the path ticker. Say whether a malformed path ticker returns 400, or 404 / an empty result.
- **L2. Ordering (§8):** Specify the order of `positions` in `/api/portfolio` (e.g. by `market_value` desc), so the table and tests are stable.
- **L3. `POST /api/watchlist` response (§8):** Say the body is a single entry with the same shape as an item in `GET /api/watchlist` (`ticker, price, open_price, added_at`).
- **L4. Connection status semantics (§2, §12):** `EventSource` retries forever and only goes `CLOSED` on a non-200 or wrong content type. Define it as: green on `open`; yellow while `readyState === CONNECTING`; red if `CLOSED` or still not reconnected after ~10s.
- **L5. Sparkline memory (§10):** "Accumulated since page load" is unbounded. Cap it at, e.g., the last 300 points per ticker.
- **L6. SSE keep-alive (§6):** In Massive mode the stream can be silent for 15s or more. Send a `: ping\n\n` comment every ~15s so proxies (App Runner/Render) don't drop idle connections. That needs a small change in `stream.py`.
- **L7. `stream.py` module-level router (§6 code):** `create_stream_router` adds a route to a module-global `router`. Calling it twice (e.g. in API tests that build several apps) registers duplicate routes bound to the first cache. Create the `APIRouter` inside the factory. Add this to the [change] list.
- **L8. `MASSIVE_POLL_INTERVAL` validation (§5):** Say that an unparseable or < 1 value falls back to 15 with a warning.
- **L9. Watchlist size cap (§7):** The simulator rebuilds an O(n²) Cholesky matrix on every add (its comment assumes n < 50), and the LLM can add tickers freely. Consider capping the watchlist at 50 (400 "Watchlist is full").
- **L10. Failed chat requests (§8):** On a 502, the user message is stored but there is no reply. Say whether the frontend shows the error inline and whether the orphaned user message appears on reload. That's acceptable, but state it.
- **L11. Realized P&L (§2):** It isn't tracked anywhere. The total value captures it implicitly. Say "not shown" so no agent invents a column.
- **L12. Reset during an in-flight chat (§8):** A chat response can land after a reset and write trades or messages into the fresh account. Under the H4 lock this is acceptable, but the frontend should disable Reset while a chat request is pending.

---

## Testing gaps (§12)

Add these to the backend list:
- Seeding: a removed default ticker stays removed after restart (H1).
- Chat: history passed to the LLM has no duplicate of the new message (H2). An LLM timeout returns 502 and the user message is persisted.
- Concurrency: two concurrent buys that together exceed cash; exactly one succeeds (H4).
- Snapshots: multiple trades in one chat response produce distinct, ascending `recorded_at` values (H3).
- Error shape: 400/404/502/503 bodies use `{"error": ...}` (M3).
- Reset: removes non-default tickers from the market source and clears their history and open price (M1).

Add these to the frontend list:
- Chart data dedupe/sort helper (H3).
- Flash fires only when the price changes (M10).
- Percent formatting (H6).

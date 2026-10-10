# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

Built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area, pre-filled with the last ~5 minutes of prices from the backend
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, unrealized P&L %
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat
- **Reset the account** — one click restores $10,000 cash, the default watchlist, and clears positions, trades, snapshots and chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving        │
│                      (Next.js export)           │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background tasks: market data poller/simulator,│
│                    portfolio snapshot timer     │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Startup

All initialization happens once in FastAPI's `lifespan` hook, before the server accepts requests:

1. Create the database schema and seed default data (idempotent — see §7)
2. Start the market data source, tracking the watchlist ∪ held positions (see §6)
3. Record an initial portfolio snapshot, then start the 30-second snapshot task

No work is deferred to the first request; this avoids races between concurrent first requests.

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Stdlib `sqlite3`, no ORM | Six small tables and simple queries; an ORM adds more than it saves |
| Single Docker container | Students run one command; no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |
| Non-streaming chat responses | Structured output must be complete before it can be parsed and executed; Cerebras returns in 1–3s, so a loading indicator is enough |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── app/
│       ├── market/           # Market data subsystem (complete)
│       └── db/               # schema.sql, seed data, connection helpers
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch app via docker compose (macOS/Linux)
│   ├── stop_mac.sh           # Stop app (macOS/Linux)
│   ├── start_windows.ps1     # Launch app via docker compose (Windows PowerShell)
│   └── stop_windows.ps1      # Stop app (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Local-dev SQLite location (finally.db is gitignored)
│   └── .gitkeep
├── Dockerfile                # Multi-stage build (Node → Python)
├── docker-compose.yml        # Single source of truth for container config
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/app/db/`** contains `schema.sql`, seed logic and connection helpers. Schema creation and seeding run at startup (§3).
- **`db/`** at the top level is where the SQLite file lives during local development. In Docker, the file lives in a named volume mounted at `/app/db` (§11).
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap `docker compose`.

---

## 5. Environment Variables

```bash
# Required for real LLM chat: OpenRouter API key
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional: seconds between Massive polls (default 15, suits the free tier)
MASSIVE_POLL_INTERVAL=15

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false

# Optional: SQLite file path. Defaults to <repo>/db/finally.db locally;
# the Dockerfile sets it to /app/db/finally.db
DB_PATH=
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data, polling every `MASSIVE_POLL_INTERVAL` seconds
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (§9)
- If `OPENROUTER_API_KEY` is missing and `LLM_MOCK` is not `true` → the app starts normally; `POST /api/chat` returns `503` with `{"error": "AI assistant is not configured. Set OPENROUTER_API_KEY in .env."}`

### Loading

- **Docker**: variables are injected by `docker compose` via `env_file: .env`. No `.env` file exists inside the container.
- **Local dev**: the backend loads `../.env` (the project root) with `python-dotenv` if the file exists. Variables already set in the environment take precedence.

---

## 6. Market Data

> **Status:** The market data subsystem is built and tested (`backend/app/market/`, see `planning/MARKET_DATA_SUMMARY.md`). Changes required by this plan are marked **[change]**.

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface (`MarketDataSource`: `start/stop/add_ticker/remove_ticker/get_tickers`). The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.); unknown tickers start at a random price between $50 and $300
- A newly added ticker is priced immediately
- Runs as an in-process background task — no external dependencies

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- Polls for all tracked tickers every `MASSIVE_POLL_INTERVAL` seconds (default 15, suits the free tier's 5 calls/min; paid tiers can use 2–15) **[change: factory reads the env var]**
- A newly added ticker has no price until the next poll
- Parses REST response into the same format as the simulator

### Tracked Tickers

The set of tickers the market data source prices is **watchlist ∪ held positions**. Otherwise, removing a held ticker from the watchlist would stop its prices and break portfolio valuation.

- **Watchlist add** → call `market_source.add_ticker(ticker)`
- **Watchlist remove** → call `market_source.remove_ticker(ticker)` only if no position is held
- **Sell to zero** → if the ticker is not on the watchlist, call `market_source.remove_ticker(ticker)`
- **Startup** → start the source with watchlist ∪ positions

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache
- The cache holds, per ticker: latest price, previous price, timestamp, and **session open price** — the first price recorded for that ticker since the process started **[change]**
- The cache also keeps a **price history ring buffer** per ticker: the last 5 minutes of `(timestamp, price)` points (600 points at 500ms) **[change]**. Served by `GET /api/prices/{ticker}/history` (§8) so the main chart isn't empty on load or after switching tickers.
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### "Change %" Definition

There is no trading day in the simulator, so the watchlist's change % is measured from the **session open price**: `(price - open_price) / open_price * 100`. The UI labels this column **"Chg %"** rather than "Daily". The existing `change_percent` field in the SSE payload is the tick-to-tick change and is used only for flash direction, not display.

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- The server first sends `retry: 1000` so the browser reconnects 1 second after a drop
- About every 500ms, if any price changed, the server sends **one event containing all tracked tickers**, keyed by ticker:

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.52, "previous_price": 190.41, "open_price": 190.00, "timestamp": 1760000000.123, "change": 0.11, "change_percent": 0.0578, "direction": "up"}, "GOOGL": {...}, ...}
```

| Field | Type | Notes |
|---|---|---|
| `ticker` | string | Uppercase symbol |
| `price` | number | Rounded to 2 decimals |
| `previous_price` | number | Price at the previous tick |
| `open_price` | number | Session open price **[change: new field]** |
| `timestamp` | number | **Unix seconds (float)** — unlike REST/DB timestamps, which are ISO 8601 |
| `change` | number | `price - previous_price` |
| `change_percent` | number | Tick-to-tick % change |
| `direction` | string | `"up"`, `"down"` or `"flat"` |

---

## 7. Database

### SQLite, Initialized at Startup

The database file lives at `DB_PATH` (§5). At startup (§3), the backend runs `schema.sql` (every statement is `CREATE TABLE IF NOT EXISTS`) and then inserts seed rows with `INSERT OR IGNORE`. This is idempotent, so:

- No separate migration step
- No "is the database empty?" detection
- Fresh Docker volumes start with a clean, seeded database automatically

Use the stdlib `sqlite3` module directly — no ORM.

### Conventions

- All REST/DB timestamps are ISO 8601 UTC strings (e.g. `2026-10-09T14:03:22Z`)
- Tickers are stored uppercase and trimmed
- Snapshots and trades are never pruned (a snapshot every 30s is ~2,900 rows/day, trivial for SQLite)

### Schema

All tables except `users_profile` include a `user_id` column defaulting to `"default"` (`users_profile` uses `id` as the user key). The user is hardcoded to `"default"` for now (single-user), but this enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded at startup, every 30 seconds by a background task, immediately after each trade, and after a reset.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — see `actions` shape in §8; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

### Trade Rules

Shared by manual trades and LLM trades:

- **Ticker**: trimmed and uppercased; must match `^[A-Z][A-Z0-9.]{0,9}$`. Any well-formed symbol is accepted (the simulator prices anything).
- **Quantity**: must be > 0; rounded to 4 decimal places.
- **Price**: the current price from the cache. If the ticker has no cached price → reject with "No price available for {ticker}. Add it to your watchlist first."
- **Buy**: requires `quantity * price <= cash_balance`. New avg cost = `(old_qty * old_avg + qty * price) / (old_qty + qty)`.
- **Sell**: requires `quantity <= held quantity` (with a `1e-6` tolerance). Avg cost is unchanged.
- **Dust**: if the remaining quantity is below `1e-6`, delete the position row. It disappears from the positions table and heatmap immediately.
- Each trade runs in one SQLite transaction (cash, position, trade log), followed by a snapshot.

---

## 8. API Endpoints

### Conventions

- Request/response bodies are JSON.
- **Business-rule failures** (insufficient cash or shares, bad quantity, malformed ticker, no price) return `400` with `{"error": "<human-readable message>"}`.
- **Malformed request bodies** (missing field, wrong type) return FastAPI's default `422`.
- **Not found** returns `404` with `{"error": "..."}`.

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates (§6) |
| GET | `/api/prices/{ticker}/history` | Last ~5 minutes of prices for one ticker |

`GET /api/prices/{ticker}/history` → `200` (empty `points` for an untracked ticker)
```json
{"ticker": "AAPL", "points": [{"timestamp": 1760000000.0, "price": 190.41}, {"timestamp": 1760000000.5, "price": 190.52}]}
```
Timestamps are Unix seconds, matching the SSE stream, so the frontend can append SSE points directly.

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |
| POST | `/api/reset` | Reset the account to its seeded state |

`GET /api/portfolio` → `200`
```json
{
  "cash_balance": 8095.00,
  "positions_value": 1905.20,
  "total_value": 10000.20,
  "unrealized_pnl": 0.20,
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10,
      "avg_cost": 190.50,
      "current_price": 190.52,
      "market_value": 1905.20,
      "unrealized_pnl": 0.20,
      "unrealized_pnl_percent": 0.0105,
      "weight": 1.0
    }
  ]
}
```
- `weight` = position market value / `positions_value` (used to size heatmap tiles).
- If a held ticker has no cached price yet, `current_price` falls back to `avg_cost`.
- The positions table's "% change" column is `unrealized_pnl_percent`.

`POST /api/portfolio/trade` with `{"ticker": "AAPL", "quantity": 10, "side": "buy"}` → `200`
```json
{
  "trade": {"id": "…", "ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.50, "executed_at": "2026-10-09T14:03:22Z"},
  "portfolio": { "...": "same shape as GET /api/portfolio" }
}
```
Returning the updated portfolio means the frontend doesn't need to re-fetch after a manual trade.

`GET /api/portfolio/history` → `200`, oldest first
```json
{"snapshots": [{"total_value": 10000.0, "recorded_at": "2026-10-09T14:00:00Z"}]}
```

`POST /api/reset` → `200` `{"status": "ok"}`. In one transaction: cash back to 10000, delete all positions, trades, snapshots and chat messages, and restore the default watchlist. Then re-sync tracked tickers to the default watchlist and record a fresh snapshot.

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

`GET /api/watchlist` → `200`, in `added_at` order
```json
{"tickers": [{"ticker": "AAPL", "price": 190.52, "open_price": 190.00, "added_at": "2026-10-09T14:00:00Z"}]}
```
`price` and `open_price` are `null` until the first price arrives (possible in Massive mode).

- `POST /api/watchlist` → `201` with the new entry; adding a ticker already on the list returns `200` with the existing entry (idempotent); a malformed ticker returns `400`.
- `DELETE /api/watchlist/{ticker}` → `204`; `404` if the ticker isn't on the watchlist.

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |
| GET | `/api/chat/history` | Recent messages, for repopulating the chat panel on page load |

`POST /api/chat` with `{"message": "Buy 5 NVDA"}` → `200`, returning the stored assistant message:
```json
{
  "id": "…",
  "role": "assistant",
  "content": "Bought 5 NVDA at $875.20. NVDA is now 30% of your portfolio.",
  "actions": {
    "trades": [{"ticker": "NVDA", "side": "buy", "quantity": 5, "status": "executed", "price": 875.20}],
    "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed", "error": "…"}]
  },
  "created_at": "2026-10-09T14:03:22Z"
}
```
- Each action has `status`: `"executed"` or `"failed"`; failed actions include `error`. Executed trades include `price`.
- `actions` is `null` when the LLM requested no actions.
- If the LLM call fails or returns unparseable output → `502` with `{"error": "..."}`; the user message is still stored.

`GET /api/chat/history` → `200`, the last 50 messages, oldest first
```json
{"messages": [{"id": "…", "role": "user", "content": "Buy 5 NVDA", "actions": null, "created_at": "…"}]}
```

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) → `200` `{"status": "ok"}` |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use cerebras-inference skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Stores the user message in `chat_messages`
2. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
3. Loads the last 20 messages from `chat_messages` as conversation history
4. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
5. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
6. Parses the complete structured JSON response
7. Executes actions (see Auto-Execution below)
8. Appends a note to the message for any failed actions (see Reporting Failures)
9. Stores the assistant message and executed actions in `chat_messages`
10. Returns the stored assistant message as JSON (§8)

The response is returned whole, not streamed token-by-token: structured output can't be parsed or executed until it's complete, and Cerebras returns in 1–3 seconds, so a loading indicator is sufficient.

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. Each trade goes through the same Trade Rules as manual trades (§7)
- `watchlist_changes` (optional): Array of watchlist modifications (`action` is `"add"` or `"remove"`)

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

Execution order and failure handling:
- Watchlist changes run first, then trades, so a trade can use a ticker the same response just added (the simulator prices new tickers immediately).
- Each action runs independently, in the order given. A failure doesn't stop the remaining actions.
- Each action's outcome (`executed` or `failed` with `error`) is recorded in `actions` (§8).

### Reporting Failures

The LLM writes its message before any action executes, so it can't know about failures. The backend appends a templated note to the message for each failed action, e.g.:

> ⚠️ Couldn't buy 50 TSLA: insufficient cash (need $12,450.00, have $8,095.00).

No second LLM call is made.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

The mock matches the user message case-insensitively, first rule wins:

| Message contains | Mock response |
|---|---|
| `buy` | message "Buying 1 share of AAPL.", trades `[{"ticker": "AAPL", "side": "buy", "quantity": 1}]` |
| `sell` | message "Selling 1 share of AAPL.", trades `[{"ticker": "AAPL", "side": "sell", "quantity": 1}]` |
| `add <TICKER>` | message "Adding <TICKER> to your watchlist.", watchlist_changes `[{"ticker": "<TICKER>", "action": "add"}]` |
| `remove <TICKER>` | message "Removing <TICKER> from your watchlist.", watchlist_changes `[{"ticker": "<TICKER>", "action": "remove"}]` |
| anything else | message "Hello! I'm FinAlly, your AI trading assistant. How can I help?" and no actions |

Mock responses flow through the same execution, failure-note and storage path as real ones.

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), **Chg %** since session open (§6), and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here. On selection, load `GET /api/prices/{ticker}/history`, then append SSE points.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by `weight`, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `GET /api/portfolio/history`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, unrealized P&L %
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill. Show `400` error messages inline.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history (loaded from `GET /api/chat/history` on page load), loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations, with failed actions visibly distinct.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance, and a Reset button (asks for confirmation with `window.confirm`)

### Data Flow

- **Live values are computed client-side.** The header total, positions table and heatmap combine positions (from `/api/portfolio`) with SSE prices. Don't poll `/api/portfolio` or add a second stream.
- **After a manual trade**, use the `portfolio` returned by `POST /api/portfolio/trade`.
- **After a chat response with non-null `actions`**, re-fetch `/api/portfolio`, `/api/watchlist` and `/api/portfolio/history`.
- **After a reset**, re-fetch everything and clear the chat panel and sparklines.

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- **Charts**: use **Lightweight Charts** (canvas, built for financial time series) for the main price chart and the P&L chart. Draw sparklines as a plain inline SVG polyline (no library). Build the heatmap with a small in-house squarified-treemap layout rendered as positioned divs. No other charting libraries.
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - ENV DB_PATH=/app/db/finally.db
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

### docker-compose.yml

`docker-compose.yml` is required and is the single source of truth for container config: image build, port `8000:8000`, `env_file: .env`, and a named volume `finally-data` mounted at `/app/db` for SQLite persistence.

```bash
docker compose up -d --build
```

### Start/Stop Scripts

The scripts are thin wrappers around `docker compose`, so port, volume and env settings aren't duplicated:

**`scripts/start_mac.sh`** (macOS/Linux):
- Runs `docker compose up -d` (adds `--build` if `--build` is passed or the image doesn't exist)
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Runs `docker compose down`
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: ✅ complete (73 tests in `backend/tests/market/`). Add tests only for the **[change]** items in §6: session open price, price history ring buffer, `MASSIVE_POLL_INTERVAL`.
- Tracked tickers: watchlist removal keeps a held ticker priced; selling to zero drops an unwatched ticker
- Portfolio: trade execution logic, avg cost, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss, dust removal, no cached price)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, independent execution of actions with partial failures, failure notes appended, mock-mode triggers
- API routes: status codes and response shapes from §8, error handling, reset

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Connection status indicator transitions (connected → reconnecting → connected, and disconnected)
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering, failed-action rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: Tests run with `LLM_MOCK=true` by default for speed and determinism. Each test starts with `POST /api/reset` for isolation.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send "buy", receive a response, trade execution appears inline
- Reset: after trading, reset restores $10k and the default watchlist

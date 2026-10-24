# FinAlly — Team Contracts

Shared agreement for the agent team building the rest of FinAlly. `PLAN.md` is the product spec; this file pins down **who owns which files** and **the Python interfaces between backend modules**, so teammates can build in parallel. If you need to change an interface here, message the owner(s) of the affected modules first, then update this file.

All agents work in the same working tree on branch `agent-teams`. Only touch files you own. Do not commit — the lead commits.

## Ownership

| Member | Owns |
|---|---|
| **Database Engineer** (`db-engineer`) | `backend/app/db/**`, `backend/tests/db/**` |
| **Backend API Engineer** (`backend-engineer`) | `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/**` (except `chat.py`), `backend/app/portfolio/**`, `backend/app/market/**` (if any changes are needed), `backend/pyproject.toml` + `uv.lock`, `backend/tests/api/**`, `backend/tests/portfolio/**`, `backend/tests/conftest.py`, `backend/CLAUDE.md`, `backend/README.md` |
| **LLM Engineer** (`llm-engineer`) | `backend/app/llm/**`, `backend/app/api/chat.py`, `backend/tests/llm/**` |
| **Frontend Engineer** (`frontend-engineer`) | `frontend/**` |
| **DevOps Engineer** (`devops-engineer`) | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/**`, `.env.example`, `.gitignore`, `db/.gitkeep`, root `README.md` |
| **Integration Tester** (`integration-tester`) | `test/**` |

Dependencies: `litellm` and `python-dotenv` are already in `backend/pyproject.toml`. To add another Python dependency, ask `backend-engineer` (single owner of `uv.lock` avoids lock conflicts).

## Backend Package Layout

```
backend/app/
├── main.py            # FastAPI app + lifespan (backend-engineer)
├── config.py          # dotenv loading, DB_PATH, STATIC_DIR, LLM_MOCK helpers (backend-engineer)
├── market/            # done
├── db/                # db-engineer
├── portfolio/         # trade rules, valuation, tracked tickers, snapshots (backend-engineer)
├── llm/               # prompt, LiteLLM client, mock, chat orchestration (llm-engineer)
└── api/               # routers: portfolio.py, watchlist.py, system.py (backend-engineer); chat.py (llm-engineer)
```

## Shared Runtime State

`main.py` builds one `AppState` and stores it on `app.state.ctx`. Routers get it from `request.app.state.ctx`.

```python
# backend/app/state.py  (backend-engineer)
@dataclass
class AppState:
    db_path: str
    price_cache: PriceCache
    market_source: MarketDataSource
```

## `app.db` (db-engineer)

Stdlib `sqlite3` only. All functions take an open `sqlite3.Connection` as the first argument, except `connect` / `init_db`. Row results are plain `dict`s. Timestamps are ISO 8601 UTC with `Z` suffix, seconds precision (`2026-10-09T14:03:22Z`). Every function defaults `user_id="default"`. Functions **do not commit** unless noted — the caller controls transactions (so a trade's cash/position/trade-log writes are one transaction).

```python
DEFAULT_USER = "default"
DEFAULT_CASH = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

def connect(db_path: str) -> sqlite3.Connection        # row_factory set, foreign keys on, WAL; creates parent dir
def init_db(db_path: str) -> None                      # run schema.sql + INSERT OR IGNORE seeds; commits; idempotent
def now_iso() -> str
@contextmanager
def transaction(conn) -> Iterator[Connection]          # BEGIN IMMEDIATE ... COMMIT / ROLLBACK

# users_profile
def get_cash(conn, user_id=...) -> float
def set_cash(conn, cash: float, user_id=...) -> None

# watchlist  (dict: {"ticker", "added_at"})
def list_watchlist(conn, user_id=...) -> list[dict]          # added_at order (ties broken by rowid)
def get_watchlist_entry(conn, ticker, user_id=...) -> dict | None
def add_watchlist(conn, ticker, user_id=...) -> tuple[dict, bool]   # (entry, created); idempotent
def remove_watchlist(conn, ticker, user_id=...) -> bool      # False if not present

# positions  (dict: {"ticker", "quantity", "avg_cost", "updated_at"})
def list_positions(conn, user_id=...) -> list[dict]          # ticker order
def get_position(conn, ticker, user_id=...) -> dict | None
def upsert_position(conn, ticker, quantity, avg_cost, user_id=...) -> None
def delete_position(conn, ticker, user_id=...) -> None

# trades  (dict: {"id", "ticker", "side", "quantity", "price", "executed_at"})
def insert_trade(conn, ticker, side, quantity, price, user_id=...) -> dict

# portfolio_snapshots  (dict: {"total_value", "recorded_at"})
def insert_snapshot(conn, total_value, user_id=...) -> dict
def list_snapshots(conn, user_id=...) -> list[dict]          # oldest first

# chat_messages  (dict: {"id", "role", "content", "actions", "created_at"}; actions decoded from JSON or None)
def insert_chat_message(conn, role, content, actions: dict | None = None, user_id=...) -> dict
def list_chat_messages(conn, limit: int = 50, user_id=...) -> list[dict]   # the last `limit`, oldest first

# reset
def reset_user(conn, user_id=...) -> None   # cash=10000, delete positions/trades/snapshots/chat, restore default watchlist
```

Seeded default watchlist rows must keep the order above when listed by `added_at` (e.g. stagger their timestamps or rely on rowid tie-break).

Implementation notes (db-engineer):
- `connect()` returns an **autocommit** connection (`isolation_level=None`, `check_same_thread=False`). A write outside `with transaction(conn):` commits immediately, and `conn.commit()` does nothing. Wrap multi-write operations (trades, `reset_user`) in `transaction()`.
- `init_db` seeds the default watchlist only when it first creates the user profile, so a default ticker the user removed is not re-added on restart. `reset_user` restores the default watchlist.
- Repository functions strip and uppercase tickers defensively. Validation (`normalize_ticker`) is still the caller's job.
- `get_cash` raises `LookupError` if the profile row is missing.

## `app.portfolio` (backend-engineer)

Implements PLAN §7 Trade Rules and §6 Tracked Tickers. Used by both the REST routes and the LLM engineer's chat orchestration.

```python
class TradeError(Exception): ...          # message is the human-readable 400 error text

def normalize_ticker(raw: str) -> str      # strip + upper, validate ^[A-Z][A-Z0-9.]{0,9}$; raises TradeError

def build_portfolio(conn, price_cache) -> dict          # exact GET /api/portfolio shape (PLAN §8)
def record_snapshot(conn, price_cache) -> dict           # computes total value, inserts, commits

async def execute_trade(state: AppState, ticker: str, side: str, quantity: float) -> dict
    # validates + executes in one transaction, records a snapshot, drops an unwatched ticker sold to zero;
    # returns the trade dict; raises TradeError

async def add_to_watchlist(state, ticker) -> tuple[dict, bool]   # normalizes, persists, market_source.add_ticker
async def remove_from_watchlist(state, ticker) -> bool           # persists; remove_ticker only if no position held
async def reset_account(state) -> None                           # db.reset_user, re-sync tracked tickers, snapshot
```

Watchlist errors (malformed ticker) also raise `TradeError` (or a sibling subclass of a common `PortfolioError`) whose message is user-facing.

## `app.llm` (llm-engineer)

```python
async def handle_chat(state: AppState, message: str) -> dict
    # PLAN §9 steps 1–10; returns the stored assistant message dict (PLAN §8 shape)
class LLMNotConfigured(Exception)   # -> 503 with PLAN §5 message
class LLMCallFailed(Exception)      # -> 502
```

`backend/app/api/chat.py` exposes `router` with `POST /api/chat` and `GET /api/chat/history`; `main.py` includes it. Use `asyncio.to_thread` (or `litellm.acompletion`) so the LLM call doesn't block the event loop. Actions call `app.portfolio.add_to_watchlist / remove_from_watchlist / execute_trade` — never the DB directly for trades.

## Errors

`main.py` registers a handler so routers can raise `HTTPException(status, detail=msg)` and the response body is `{"error": msg}` (PLAN §8). Validation errors stay FastAPI's default 422.

## Static Frontend

- `frontend/next.config` uses `output: 'export'`; build output is `frontend/out/`.
- FastAPI serves static files from `STATIC_DIR` (env var; default `backend/static`) at `/`, mounted **after** all `/api` routes, with `html=True`. If the directory doesn't exist, skip the mount (API-only dev).
- The Dockerfile copies `frontend/out/` → `/app/static` and sets `STATIC_DIR=/app/static`, `DB_PATH=/app/db/finally.db`.
- In Docker the app's working dir is `/app` with the backend project at `/app` (so `uvicorn app.main:app`).

## Frontend ↔ API

The API shapes in `PLAN.md` §6 and §8 are the contract. The frontend dev server (`next dev`) should proxy `/api/*` to `http://localhost:8000` via `rewrites` in development only (rewrites are ignored by static export — guard with `process.env.NODE_ENV`).

## Testing & Ready Signals

- Every member writes unit tests for their own code and keeps `uv run --extra dev pytest` / `npm test` green.
- Backend tests use a temp DB file (`tmp_path`) — never `db/finally.db`.
- When your piece is usable, message `integration-tester` (and the lead) with what's ready and how to run it.
- `integration-tester` reports bugs directly to the owning member via message, with repro steps and the failing test name; owners fix and reply.

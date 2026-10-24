# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Running the App

```bash
uv run uvicorn app.main:app --port 8000          # from backend/; LLM_MOCK=true for mock chat
```

`app/main.py` builds the app with `create_app(db_path=None, static_dir=None, source_factory=create_market_data_source, snapshot_interval=30.0)`; arguments override the environment (tests pass a temp DB and a fake source). The lifespan runs `init_db`, starts the market source with watchlist ∪ held positions, records a snapshot, then snapshots every 30 s. `STATIC_DIR` is mounted at `/` after the API routes, and skipped if missing. Raise `HTTPException(status, detail=msg)` in routers; the global handler returns `{"error": msg}`.

## App Modules

- **`app/config.py`** — `load_env()` (loads `<repo>/.env`, never overriding the environment), `get_db_path()` (default `<repo>/db/finally.db`), `get_static_dir()` (default `backend/static`), `llm_mock_enabled()`, `openrouter_api_key()`.
- **`app/state.py`** — `AppState(db_path, price_cache, market_source)` on `app.state.ctx`; `state.connect()` opens a new DB connection (caller closes it).
- **`app/db/`** — stdlib `sqlite3` persistence (autocommit connections; group writes in `with db.transaction(conn):`).
- **`app/portfolio/`** — the only place trades and watchlist changes happen (REST and chat both call it):
  - `execute_trade(state, ticker, side, quantity)` — PLAN §7 rules in one transaction, then a snapshot; drops an unwatched ticker sold to zero from the market source. `apply_trade(conn, cache, ...)` is the synchronous core.
  - `add_to_watchlist` / `remove_from_watchlist` / `reset_account` / `sync_tracked_tickers` — keep the market source tracking watchlist ∪ positions (PLAN §6).
  - `build_portfolio`, `build_watchlist`, `watchlist_item`, `record_snapshot` — PLAN §8 response shapes.
  - Rule violations raise `TradeError` (subclass of `PortfolioError`); the message is the user-facing 400 text.
- **`app/api/`** — routers `portfolio.py` (portfolio, trade, history, reset), `watchlist.py`, `system.py` (health), `chat.py` (LLM).
- **`app/llm/`** — chat orchestration (see its docstrings).

Tests: `tests/conftest.py` provides `FakeSource` (fixed prices, no ticking), `db_path`, `price_cache`, `app_state` and `api_client` (a `TestClient` with the lifespan running).

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PricePoint, PriceUpdate, MarketDataSource, create_market_data_source
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `open_price` (session open), `timestamp`, plus properties `change`, `change_percent` (tick-to-tick, for flash direction only), `session_change_percent` (the UI's "Chg %"), `direction` ("up"/"down"/"flat"), and `to_dict()` (the SSE payload fields).

- **`PricePoint`** — Immutable `(timestamp, price)` history point with `to_dict()`.

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None) -> PriceUpdate` — timestamp defaults to receipt time and is forced to be strictly increasing per ticker
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `get_history(ticker) -> list[PricePoint]` — last 5 minutes (max 600 points), oldest first; `[]` if unknown
  - `remove(ticker)` — also clears session open price and history
  - `version` property — monotonic counter, bumped on every update and removal (for SSE change detection)
  - Keys are stored as given: pass normalized (uppercase, trimmed) tickers.

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`. Sources normalize tickers. Only call `remove_ticker` when no position is held (tracked tickers = watchlist ∪ positions, PLAN §6).

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set (polling every `MASSIVE_POLL_INTERVAL` seconds, default 15, minimum 1), otherwise `SimulatorDataSource`.

### Massive Modes

- **Live**: one multi-ticker snapshot call per poll. Price = last trade → minute bar → day close → previous close.
- **EOD**: keys without snapshot access (the free Basic plan) switch to end-of-day closes from the grouped-daily endpoint, refreshed hourly. Prices are flat.

### Endpoints

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns a new FastAPI APIRouter
# GET /api/stream/prices                (text/event-stream; keep-alive comment every 15 s of silence)
# GET /api/prices/{ticker}/history      ({"ticker", "points": [{"timestamp", "price"}]})
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`. Other tickers get a deterministic seed price in [$50, $300) derived from the symbol.

## Running Tests

```bash
uv run --extra dev pytest -v                     # All tests
uv run --extra dev pytest --cov=app              # With coverage
uv run --extra dev ruff check app/ tests/        # Lint
uv run --extra dev ruff format --check app/ tests/  # Formatting
```

Massive tests build fixtures with the real `massive` model classes (`TickerSnapshot.from_dict(...)`), never `MagicMock` snapshots, so a wrong attribute name fails the test.

## Demo

```bash
uv run --extra dev market_data_demo.py   # Live terminal dashboard with simulated prices
```

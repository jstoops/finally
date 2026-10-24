# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation.

## Structure

- `app/` - Application code
  - `main.py` - FastAPI app factory and lifespan (startup, snapshot task, static files)
  - `config.py` - Environment loading (`.env`, `DB_PATH`, `STATIC_DIR`, LLM flags)
  - `state.py` - `AppState` shared by routers
  - `api/` - REST routers: portfolio, watchlist, system, chat
  - `portfolio/` - Trade rules, valuation, tracked tickers, snapshots, reset
  - `db/` - SQLite schema, seed data and queries
  - `llm/` - LLM chat orchestration
  - `market/` - Market data subsystem
    - `models.py` - PriceUpdate and PricePoint dataclasses
    - `cache.py` - Thread-safe price cache (latest price, session open, 5-minute history)
    - `interface.py` - MarketDataSource abstract interface
    - `simulator.py` - GBM-based market simulator
    - `massive_client.py` - Massive/Polygon.io REST poller (live snapshots, or end-of-day closes on free keys)
    - `factory.py` - Data source factory
    - `stream.py` - SSE streaming and price-history endpoints
    - `seed_prices.py` - Default ticker prices and parameters

- `tests/` - Unit and integration tests
  - `market/`, `db/`, `portfolio/`, `api/`, `llm/`

## Running the App

```bash
uv sync --extra dev
uv run uvicorn app.main:app --port 8000   # http://localhost:8000/api/health
```

## Running Tests

```bash
# Install dependencies
uv sync --extra dev

# Run all tests
uv run --extra dev pytest

# Run with coverage
uv run --extra dev pytest --cov=app --cov-report=html

# Run specific test file
uv run --extra dev pytest tests/market/test_simulator.py

# Run with verbose output
uv run --extra dev pytest -v
```

## Environment Variables

- `MASSIVE_API_KEY` - Optional. If set, use real market data from Massive API. If not set, use the built-in simulator.
- `MASSIVE_POLL_INTERVAL` - Optional. Seconds between Massive polls (default 15, minimum 1).
- `DB_PATH` - Optional. SQLite file (default `<repo>/db/finally.db`).
- `STATIC_DIR` - Optional. Static frontend served at `/` (default `backend/static`; skipped if missing).
- `OPENROUTER_API_KEY`, `LLM_MOCK` - LLM chat (see `planning/PLAN.md` §5).

Locally, `<repo>/.env` is loaded if present; variables already set in the environment win.

## Development

```bash
# Install dependencies
uv sync --extra dev

# Run linter
uv run --extra dev ruff check .

# Format code
uv run --extra dev ruff format .
```

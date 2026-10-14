# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

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

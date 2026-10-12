# FinAlly — AI Trading Workstation

An AI-powered trading terminal: live streaming prices, a simulated $10,000 portfolio, and an LLM copilot that analyzes positions and executes trades through chat. Built entirely by coding agents.

> **Status:** the market data subsystem (`backend/app/market/`) is complete and tested. The API, frontend, Docker setup and scripts are still to be built — see [`planning/PLAN.md`](planning/PLAN.md) for the full spec.

## Features (planned)

- Live prices over SSE with flash animations and sparklines
- Market orders with instant fills — no fees, no login
- Portfolio heatmap, P&L chart and positions table
- AI chat assistant that trades and manages the watchlist
- One-click account reset

## Stack

Next.js (static export, TypeScript, Tailwind) · FastAPI + uv · SQLite · SSE · LiteLLM → OpenRouter (Cerebras) · one Docker container on port 8000.

## Development

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest -v   # run tests
uv run market_data_demo.py     # terminal demo of the price simulator
```

Once the container is built, the app will run with `docker compose up -d --build` at http://localhost:8000.

## Configuration

Set in `.env` at the project root:

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Enables AI chat |
| `MASSIVE_API_KEY` | empty | Real market data via Massive (Polygon.io); simulator if unset |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive polls |
| `LLM_MOCK` | `false` | Deterministic mock LLM responses for testing |
| `DB_PATH` | `db/finally.db` | SQLite file location |

## Layout

```
backend/    FastAPI uv project (market data complete)
planning/   Specs and agent docs
frontend/   Next.js app (to come)
test/       Playwright E2E tests (to come)
```

## License

See [LICENSE](LICENSE).

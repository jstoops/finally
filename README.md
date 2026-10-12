# FinAlly — AI Trading Workstation

An AI-powered trading terminal: live streaming prices, a simulated $10,000 portfolio, and an LLM copilot that can analyze your positions and execute trades through chat. Built entirely by coding agents.

> **Status:** the market data subsystem is complete; the rest of the platform is in progress. See [`planning/PLAN.md`](planning/PLAN.md) for the full spec.

## Features

- Live prices over SSE with green/red flash animations and sparklines
- Market orders with instant fills — no fees, no login
- Portfolio heatmap, P&L chart and positions table
- AI chat assistant that trades and manages your watchlist
- One-click account reset

## Quick Start

```bash
cp .env.example .env          # add your OPENROUTER_API_KEY
docker compose up -d --build  # or scripts/start_mac.sh / scripts/start_windows.ps1
```

Open http://localhost:8000. Stop with `docker compose down` (data persists in the `finally-data` volume).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Enables AI chat (chat returns 503 without it) |
| `MASSIVE_API_KEY` | empty | Real market data via Massive (Polygon.io); simulator if unset |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive polls |
| `LLM_MOCK` | `false` | Deterministic mock LLM responses for testing |
| `DB_PATH` | `db/finally.db` | SQLite file location |

## Stack

Next.js (static export, TypeScript, Tailwind) · FastAPI + uv · SQLite · SSE · LiteLLM → OpenRouter (Cerebras) · single Docker container on port 8000.

## Development

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest -v      # backend tests
uv run market_data_demo.py        # terminal demo of the price simulator
```

## Layout

```
frontend/   Next.js app
backend/    FastAPI uv project
planning/   Specs and agent docs
scripts/    Start/stop wrappers for docker compose
test/       Playwright E2E tests
db/         Local SQLite location
```

## License

See [LICENSE](LICENSE).

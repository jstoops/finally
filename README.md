# FinAlly — AI Trading Workstation

An AI-powered trading terminal: live streaming prices, a simulated $10,000 portfolio, and an LLM copilot that analyzes positions and executes trades through chat. Built entirely by coding agents — see [`planning/PLAN.md`](planning/PLAN.md) for the full spec.

## Features

- Live prices over SSE with flash animations and sparklines
- Market orders with instant fills — no fees, no login
- Portfolio heatmap, P&L chart and positions table
- AI chat assistant that trades and manages the watchlist
- One-click account reset

## Quick Start

Requires Docker.

```bash
cp .env.example .env          # add your OPENROUTER_API_KEY
./scripts/start_mac.sh        # macOS/Linux
.\scripts\start_windows.ps1   # Windows PowerShell
```

Open http://localhost:8000. The start scripts build the image on first run (or with `--build` / `-Build`) and open the browser (skip with `--no-open` / `-NoOpen`). Stop with `scripts/stop_mac.sh` or `scripts\stop_windows.ps1`; your data persists in the `finally-data` volume.

Without the scripts: `docker compose up -d --build` and `docker compose down`. To wipe all data: `docker compose down -v`.

## Configuration

Set in `.env` at the project root (all optional; the app starts without it):

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Enables AI chat (otherwise `/api/chat` returns 503) |
| `MASSIVE_API_KEY` | empty | Real market data via Massive (Polygon.io); simulator if unset |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive polls |
| `LLM_MOCK` | `false` | Deterministic mock LLM responses for testing |
| `DB_PATH` | `db/finally.db` | SQLite file for local dev (always `/app/db/finally.db` in Docker) |

## Development

Backend (FastAPI, uv) on port 8000:

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000
uv run --extra dev pytest -v
```

Frontend (Next.js) dev server, proxying `/api/*` to the backend:

```bash
cd frontend
npm install
npm run dev
npm test
```

To serve the built frontend from the local backend, run `npm run build` and point `STATIC_DIR` at `frontend/out`.

## Tests

- Backend unit tests: `uv run --extra dev pytest` in `backend/`
- Frontend unit tests: `npm test` in `frontend/`
- E2E (Playwright, mocked LLM): see [`test/`](test/), run via `test/docker-compose.test.yml`

## Layout

```
backend/    FastAPI uv project (API, market data, SQLite, LLM)
frontend/   Next.js static export, served by FastAPI
test/       Playwright E2E tests
scripts/    Start/stop wrappers around docker compose
planning/   Specs and agent docs
db/         Local SQLite location (gitignored)
```

## License

See [LICENSE](LICENSE).

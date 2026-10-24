# FinAlly E2E tests

Playwright (TypeScript) suite covering PLAN.md §12 scenarios plus API-level checks of §8.

- `e2e/api/` — REST/SSE contract tests (Playwright `request`, no browser)
- `e2e/ui/` — browser scenarios against the built frontend

Every test begins with `POST /api/reset`; tests run serially (single-user app). The server
must run with `LLM_MOCK=true`.

## Local (fast iteration)

```bash
# terminal 1 — backend (serves the static frontend if backend/static or STATIC_DIR exists)
cd backend && LLM_MOCK=true uv run uvicorn app.main:app --port 8000

# terminal 2
cd test && npm install && npx playwright install chromium
npm test                  # everything
npm run test:api          # API only
BASE_URL=http://localhost:8000 npx playwright test -g "reset"
```

## Docker (CI-equivalent)

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

The `playwright` image tag must match the `@playwright/test` version in `package.json`.

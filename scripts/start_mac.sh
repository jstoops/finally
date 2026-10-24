#!/usr/bin/env bash
# Start FinAlly via docker compose. Usage: scripts/start_mac.sh [--build] [--no-open]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

URL="http://localhost:8000"
BUILD=false
OPEN_BROWSER=true

for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    --no-open) OPEN_BROWSER=false ;;
    -h|--help)
      echo "Usage: $0 [--build] [--no-open]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if [ ! -f .env ]; then
  echo "Note: no .env found; AI chat needs OPENROUTER_API_KEY (see .env.example)."
fi

# Build when asked, or when the image has never been built
if [ "$BUILD" = false ] && ! docker image inspect finally:latest >/dev/null 2>&1; then
  BUILD=true
fi

if [ "$BUILD" = true ]; then
  docker compose up -d --build
else
  docker compose up -d
fi

echo "FinAlly is running at $URL"

if [ "$OPEN_BROWSER" = true ]; then
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi

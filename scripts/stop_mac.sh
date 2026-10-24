#!/usr/bin/env bash
# Stop FinAlly. The finally-data volume is kept, so your portfolio persists.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker compose down
echo "FinAlly stopped (data volume preserved)."

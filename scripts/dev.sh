#!/usr/bin/env bash
# Start the API and one worker locally, with settings from .env (DATABASE_URL, API_PORT). Ctrl-C stops both.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$root/.env" ]; then set -a; . "$root/.env"; set +a; fi
# pytest's database must never leak into the app
unset TEST_DATABASE_URL

cd "$root/backend"
[ -f .venv/bin/activate ] && . .venv/bin/activate

if [[ "${DATABASE_URL:-}" == postgresql* ]] && command -v docker >/dev/null; then
  docker ps --format '{{.Names}}' | grep -q '^model-benchmark-pg$' || echo "warning: container model-benchmark-pg is not running (docker start model-benchmark-pg)" >&2
fi

python -m app.worker &
worker=$!
trap 'kill $worker 2>/dev/null || true' EXIT
uvicorn app.main:app --port "${API_PORT:-8000}"

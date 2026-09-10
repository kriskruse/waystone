#!/usr/bin/env bash
# Waystone dev runner: install deps, build, test, run from the repo checkout
# (no system package install). All steps must pass before the app launches —
# tests are the smoke test, exit codes are checked directly.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> brain: npm install"
cd "$ROOT/brain"
npm install

echo "==> brain: build (dist/server.mjs)"
npm run build

echo "==> brain: typecheck"
npx tsc --noEmit

echo "==> brain: tests"
npx vitest run

echo "==> poed: sync venv deps"
cd "$ROOT/poed"
uv sync --extra dev

echo "==> poed: tests"
uv run pytest

echo "==> launching waystone from repo (poed + brain)"
cd "$ROOT/poed"
exec uv run python -m poed "$@"
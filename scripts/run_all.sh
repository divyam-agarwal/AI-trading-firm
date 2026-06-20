#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
python -m agents.fundamentals.server & F=$!
python -m agents.sentiment.server & S=$!
python -m agents.debate.server & D=$!
trap 'kill $F $S $D 2>/dev/null || true' EXIT
sleep 3
python -m orchestrator.main "${1:-AAPL}"

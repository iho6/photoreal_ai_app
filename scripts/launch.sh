#!/usr/bin/env bash
# Stage-1: create .venv, install [portal] if needed, start API in tmux, open browser.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SESSION="photoreal"
API_HOST="${PHOTOREAL_API_HOST:-127.0.0.1}"
API_PORT="${PHOTOREAL_API_PORT:-8010}"
URL="http://${API_HOST}:${API_PORT}/"
VENV_PY="$ROOT/.venv/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found" >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "error: tmux is required on Linux. Install it (e.g. sudo apt install tmux) and retry." >&2
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Creating .venv ..."
  python3 -m venv "$ROOT/.venv"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

portal_ok() {
  "$VENV_PY" -c "import fastapi; import uvicorn; import dotenv" >/dev/null 2>&1
}

api_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -sf "http://${API_HOST}:${API_PORT}/api/health" >/dev/null 2>&1
  else
    return 1
  fi
}

free_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  elif command -v ss >/dev/null 2>&1; then
    local pids
    pids="$(ss -lptn "sport = :${port}" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
    for pid in $pids; do
      echo "Killing stale PID $pid on port $port"
      kill -TERM "$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
}

if portal_ok; then
  echo "skip (already installed): portal deps"
else
  echo "Installing portal deps ..."
  python -m pip install -U pip setuptools wheel
  python -m pip install -e ".[portal]"
fi

mkdir -p "$ROOT/data/logs"

API_CMD="cd \"$ROOT\" && source \"$ROOT/.venv/bin/activate\" && exec python -m photoreal.portal --host ${API_HOST} --port ${API_PORT}"

if api_ok; then
  echo "API already healthy on $URL"
elif tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already exists; ensuring api window..."
  if ! tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -qx 'api'; then
    free_port "$API_PORT"
    tmux new-window -t "$SESSION" -n api "bash -lc '$API_CMD'"
  else
    # session/window exist but health failed — free port and restart api window
    free_port "$API_PORT"
    tmux kill-window -t "$SESSION:api" 2>/dev/null || true
    tmux new-window -t "$SESSION" -n api "bash -lc '$API_CMD'"
  fi
else
  free_port "$API_PORT"
  tmux new-session -d -s "$SESSION" -n api "bash -lc '$API_CMD'"
fi

for _ in $(seq 1 30); do
  if api_ok; then
    break
  fi
  sleep 0.3
done

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "$URL" >/dev/null 2>&1 || true
fi

echo "Portal: $URL"
echo "Attach servers: tmux attach -t $SESSION"
echo "Fill credentials in the UI, then click Launch (installs weights + starts Comfy)."

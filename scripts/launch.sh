#!/usr/bin/env bash
# Stage-1: path preflight, heal/create .venv, install [portal] if needed, start API in tmux, open browser when healthy.
# Windows portable runtime (runtime/python) is Windows-only — see scripts/launch.ps1 / docs/portal.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SESSION="photoreal"
API_HOST="${PHOTOREAL_API_HOST:-127.0.0.1}"
API_PORT="${PHOTOREAL_API_PORT:-8010}"
URL="http://${API_HOST}:${API_PORT}/"
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
MIN_MAJOR=3
MIN_MINOR=11

python_version_ok() {
  local exe="$1"
  [[ -x "$exe" ]] || return 1
  "$exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (${MIN_MAJOR}, ${MIN_MINOR}) else 1)" >/dev/null 2>&1
}

resolve_host_python() {
  local name cand
  for name in python3.11 python3 python; do
    echo "Preflight: trying $name ..." >&2
    if command -v "$name" >/dev/null 2>&1; then
      cand="$(command -v "$name")"
      if python_version_ok "$cand"; then
        echo "Preflight: accepted $name -> $cand" >&2
        printf '%s\n' "$cand"
        return 0
      fi
      echo "Preflight: skip (version < ${MIN_MAJOR}.${MIN_MINOR} or unusable) -> $cand" >&2
    else
      echo "Preflight: $name not on PATH" >&2
    fi
  done
  echo "Preflight: no usable host Python found in scan" >&2
  return 1
}

test_venv_healthy() {
  VENV_UNHEALTHY_REASON=""
  if [[ ! -d "$VENV_DIR" ]]; then
    VENV_UNHEALTHY_REASON=".venv directory missing"
    return 1
  fi
  if [[ ! -x "$VENV_PY" ]]; then
    VENV_UNHEALTHY_REASON="missing bin/python"
    return 1
  fi
  if [[ -f "$VENV_DIR/pyvenv.cfg" ]]; then
    local key val
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in
        home\ =*|executable\ =*)
          key="${line%%=*}"
          key="$(echo "$key" | tr -d '[:space:]')"
          val="${line#*=}"
          val="$(echo "$val" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^["'\'']//;s/["'\'']$//')"
          if [[ "$key" == "executable" ]]; then
            if [[ -n "$val" && ! -e "$val" ]]; then
              VENV_UNHEALTHY_REASON="pyvenv.cfg executable= path missing -> $val"
              return 1
            fi
          else
            if [[ -n "$val" && ! -d "$val" && ! -x "$val/bin/python" && ! -x "$val/python" ]]; then
              VENV_UNHEALTHY_REASON="pyvenv.cfg home= path missing -> $val"
              return 1
            fi
          fi
          ;;
      esac
    done < "$VENV_DIR/pyvenv.cfg"
  fi
  if ! "$VENV_PY" --version >/dev/null 2>&1; then
    VENV_UNHEALTHY_REASON="venv python --version failed"
    return 1
  fi
  return 0
}

ensure_venv() {
  local host_py="$1"
  if test_venv_healthy; then
    echo "Preflight: .venv healthy"
    return 0
  fi
  echo "Preflight: .venv unhealthy: ${VENV_UNHEALTHY_REASON:-unknown}"
  if [[ -d "$VENV_DIR" ]]; then
    echo "Preflight: removing .venv ..."
    rm -rf "$VENV_DIR"
  fi
  echo "Preflight: creating .venv with $host_py ..."
  "$host_py" -m venv "$VENV_DIR"
  if ! test_venv_healthy; then
    echo "error: failed to create a working .venv with $host_py (${VENV_UNHEALTHY_REASON:-unknown})" >&2
    exit 1
  fi
  echo "Preflight: .venv recreated OK"
}

echo "Preflight: scanning for Python >= ${MIN_MAJOR}.${MIN_MINOR} ..."
if ! HOST_PY="$(resolve_host_python)"; then
  echo "error: python3 >= ${MIN_MAJOR}.${MIN_MINOR} not found. Install it and retry." >&2
  exit 1
fi
echo "Preflight: host Python OK -> $HOST_PY"

if ! command -v tmux >/dev/null 2>&1; then
  echo "error: tmux is required on Linux. Install it (e.g. sudo apt install tmux) and retry." >&2
  exit 1
fi

ensure_venv "$HOST_PY"

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

portal_ok() {
  # Keep in sync with photoreal.portal.install_probe.PORTAL_MODULES (incl. nacl/pynacl).
  "$VENV_PY" -c '
try:
    from photoreal.portal.install_probe import portal_deps_satisfied
    raise SystemExit(0 if portal_deps_satisfied() else 1)
except Exception:
    import importlib.util
    for m in ("fastapi", "uvicorn", "dotenv", "httpx", "nacl"):
        if importlib.util.find_spec(m) is None:
            raise SystemExit(1)
    raise SystemExit(0)
' >/dev/null 2>&1
}

api_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -sf "http://${API_HOST}:${API_PORT}/api/health" >/dev/null 2>&1
  else
    return 1
  fi
}

running_api_build() {
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi
  local json
  json="$(curl -sf "http://${API_HOST}:${API_PORT}/api/health" 2>/dev/null || true)"
  if [[ -z "$json" ]]; then
    return 1
  fi
  # Prefer python (always available in venv); fall back to sed.
  if [[ -x "$VENV_PY" ]]; then
    printf '%s' "$json" | "$VENV_PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("build") or "")' 2>/dev/null
  else
    printf '%s' "$json" | sed -n 's/.*"build"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
  fi
}

expected_api_build() {
  "$VENV_PY" -c 'from photoreal.portal.build_id import build_id; print(build_id())' 2>/dev/null
}

start_portal_api() {
  free_port "$API_PORT"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-window -t "$SESSION:api" 2>/dev/null || true
    tmux new-window -t "$SESSION" -n api "bash -lc '$API_CMD'"
  else
    tmux new-session -d -s "$SESSION" -n api "bash -lc '$API_CMD'"
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
API_ERR="$ROOT/data/logs/api.err.log"
API_OUT="$ROOT/data/logs/api.out.log"

API_CMD="cd \"$ROOT\" && source \"$VENV_DIR/bin/activate\" && exec python -m photoreal.portal --host ${API_HOST} --port ${API_PORT}"

NEED_START=1
if api_ok; then
  RUNNING_BUILD="$(running_api_build || true)"
  EXPECTED_BUILD="$(expected_api_build || true)"
  if [[ -n "$RUNNING_BUILD" && -n "$EXPECTED_BUILD" && "$RUNNING_BUILD" == "$EXPECTED_BUILD" ]]; then
    echo "API already healthy on $URL (build $RUNNING_BUILD)"
    NEED_START=0
  else
    echo "Preflight: portal API is stale (code changed) -- restarting"
    if [[ -z "$RUNNING_BUILD" ]]; then
      echo "Preflight: running API has no build fingerprint (predates persistence)"
    elif [[ -z "$EXPECTED_BUILD" ]]; then
      echo "Preflight: could not compute expected build_id from venv"
    else
      echo "Preflight: running=$RUNNING_BUILD expected=$EXPECTED_BUILD"
    fi
  fi
fi

if [[ "$NEED_START" -eq 1 ]]; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already exists; ensuring api window..."
  fi
  start_portal_api
fi

for _ in $(seq 1 30); do
  if api_ok; then
    break
  fi
  sleep 0.3
done

if ! api_ok; then
  echo "error: portal API did not become healthy at $URL" >&2
  echo "Attach servers: tmux attach -t $SESSION" >&2
  echo "API logs (if present): $API_OUT / $API_ERR" >&2
  exit 1
fi

OPEN_BUILD="$(running_api_build || true)"
OPEN_URL="$URL"
if [[ -n "$OPEN_BUILD" ]]; then
  OPEN_URL="${URL}?b=${OPEN_BUILD}"
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$OPEN_URL" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "$OPEN_URL" >/dev/null 2>&1 || true
fi

echo "Portal: $OPEN_URL"
echo "Attach servers: tmux attach -t $SESSION"
echo "Fill credentials in the UI, then click Launch (installs weights + starts Comfy)."

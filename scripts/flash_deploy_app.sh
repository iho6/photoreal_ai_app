#!/usr/bin/env bash
# Deploy one Flash app from flash_apps/<app_id>/ (bare-minimum artifact).
# Usage: bash scripts/flash_deploy_app.sh <app_id>
# Example: bash scripts/flash_deploy_app.sh character
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="${1:-${FLASH_APP_ID:-}}"
if [[ -z "$APP_ID" ]]; then
  echo "Usage: $0 <app_id>   (e.g. character)" >&2
  echo "See flash_apps/README.md" >&2
  exit 2
fi
shift || true

APP_DIR="$ROOT/flash_apps/$APP_ID"
if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: unknown Flash app $APP_ID (expected $APP_DIR)" >&2
  exit 1
fi
if [[ ! -f "$APP_DIR/endpoint.py" ]]; then
  echo "ERROR: $APP_DIR/endpoint.py missing (app not ready to deploy). See META.md." >&2
  exit 1
fi
if [[ ! -f "$APP_DIR/MANIFEST.txt" ]]; then
  echo "ERROR: $APP_DIR/MANIFEST.txt missing" >&2
  exit 1
fi

load_env_key() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then
    return 0
  fi
  if [[ -f "$ROOT/.env" ]]; then
    local line
    line="$(grep -E "^${key}=" "$ROOT/.env" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      export "${key}=${line#*=}"
    fi
  fi
}

load_env_key RUNPOD_API_KEY
load_env_key HF_TOKEN

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
  echo "ERROR: RUNPOD_API_KEY missing. Save it on the portal login page, then retry." >&2
  exit 1
fi

export RUNPOD_API_KEY
export HF_TOKEN="${HF_TOKEN:-}"
# Flash app display name (Runpod Flash app), distinct from flash_apps/<id>
export FLASH_APP="${FLASH_APP:-photoreal-${APP_ID}}"
export FLASH_ENV="${FLASH_ENV:-production}"

EXCLUDES_FILE="$ROOT/flash_apps/_shared/excludes.txt"
EXCLUDE_ARG=""
if [[ -f "$EXCLUDES_FILE" ]]; then
  EXCLUDE_ARG="$(grep -vE '^\s*(#|$)' "$EXCLUDES_FILE" | paste -sd, -)"
fi

echo "=== Flash deploy app=$APP_ID ==="
echo "FLASH_APP=$FLASH_APP FLASH_ENV=$FLASH_ENV"
echo "app_dir=$APP_DIR"
echo "repo=$ROOT"
if [[ -n "$EXCLUDE_ARG" ]]; then
  echo "exclude=$EXCLUDE_ARG"
fi

FLASH_PKG='runpod-flash>=1.19.0,<2'

if ! command -v flash >/dev/null 2>&1; then
  echo "Installing $FLASH_PKG…"
  python3 -m pip install -q "$FLASH_PKG"
fi

if ! command -v flash >/dev/null 2>&1; then
  if [[ -x "$ROOT/.venv/bin/flash" ]]; then
    export PATH="$ROOT/.venv/bin:$PATH"
  else
    python3 -m pip install -q "$FLASH_PKG"
    export PATH="$(python3 -m site --user-base)/bin:${PATH:-}"
  fi
fi

if ! command -v flash >/dev/null 2>&1; then
  echo "ERROR: flash CLI not found after install. Try: pip install runpod-flash && flash --help" >&2
  exit 1
fi

echo "Staging MANIFEST → $APP_DIR/photoreal/"
python3 "$ROOT/flash_apps/_shared/stage_from_manifest.py" "$APP_DIR" --repo "$ROOT"

# Default --no-deps: transformers' transitive tree pulls nvidia CUDA wheels that
# blow the 1.5GB limit even when listed in --exclude. Override with FLASH_NO_DEPS=0.
USE_NO_DEPS="${FLASH_NO_DEPS:-1}"

cd "$APP_DIR"
DEPLOY_CMD=(flash deploy --env "$FLASH_ENV")
if [[ -n "$EXCLUDE_ARG" ]]; then
  DEPLOY_CMD+=(--exclude "$EXCLUDE_ARG")
fi
if [[ "$USE_NO_DEPS" == "1" ]]; then
  DEPLOY_CMD+=(--no-deps)
  echo "no-deps=1 (set FLASH_NO_DEPS=0 to install transitive deps)"
fi
echo "Running: ${DEPLOY_CMD[*]}"
"${DEPLOY_CMD[@]}"

echo "=== Deploy finished (app=$APP_ID) ==="
echo "See flash_apps/$APP_ID/META.md for endpoint name and portal wiring."
echo "Models: Generate auto-checks/syncs Network Volume (or: python scripts/flash_sync_volume.py)."

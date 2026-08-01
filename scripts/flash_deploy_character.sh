#!/usr/bin/env bash
# Deploy Flash character endpoint (photoreal-character-4090) to Runpod.
# Run from WSL/Linux at repo root, or via scripts/flash_deploy_character.ps1 on Windows.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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
export FLASH_APP="${FLASH_APP:-photoreal-character}"
export FLASH_ENV="${FLASH_ENV:-production}"

echo "=== Flash deploy character endpoint ==="
echo "FLASH_APP=$FLASH_APP FLASH_ENV=$FLASH_ENV"
echo "repo=$ROOT"

FLASH_PKG='runpod-flash>=1.19.0,<2'

if ! command -v flash >/dev/null 2>&1; then
  echo "Installing $FLASH_PKG…"
  python3 -m pip install -q "$FLASH_PKG"
fi

# Ensure flash CLI is on PATH after pip install --user / venv
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

# Deploy discovers @Endpoint in the project (scripts/flash_character_endpoint.py).
echo "Running: flash deploy --env $FLASH_ENV"
flash deploy --env "$FLASH_ENV"

echo "=== Deploy finished ==="
echo "Portal will resolve endpoint name photoreal-character-4090 on next Generate."
echo "Models: Generate auto-checks/syncs volume photoreal-models (or: python scripts/flash_sync_volume.py)."

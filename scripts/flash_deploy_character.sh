#!/usr/bin/env bash
# Wrapper: deploy flash_apps/character (photoreal-character-4090).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/flash_deploy_app.sh" character "$@"

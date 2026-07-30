#!/usr/bin/env bash
# Photoreal launcher (Linux primary). Delegates to scripts/launch.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/launch.sh" "$@"

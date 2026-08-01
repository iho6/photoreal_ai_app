#!/usr/bin/env python3
"""Deprecated entrypoint — character Flash lives in flash_apps/character/.

Use::

  bash scripts/flash_deploy_app.sh character

See flash_apps/README.md and flash_apps/character/META.md.
"""

from __future__ import annotations

raise SystemExit(
    "Moved to flash_apps/character/endpoint.py — "
    "run: bash scripts/flash_deploy_app.sh character"
)

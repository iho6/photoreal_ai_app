#!/usr/bin/env python3
"""Sync / verify character models on Runpod Network Volume photoreal-models.

Uses portal .env RUNPOD_API_KEY + HF_TOKEN. Spins a short-lived pod attached to
the volume; downloads only when the completeness check fails.

Usage (repo root):
  python scripts/flash_sync_volume.py           # sync if FLASH_VOLUME_SYNCED unset
  python scripts/flash_sync_volume.py --force   # re-run fill (still skips existing files)
  python scripts/flash_sync_volume.py --check   # completeness probe only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore FLASH_VOLUME_SYNCED and re-run bootstrap (file-level skips still apply)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify models are complete on the volume (no download)",
    )
    args = parser.parse_args()

    from photoreal.flash.volume_sync import sync_volume_models

    def log(msg: str) -> None:
        print(msg, flush=True)

    sync_volume_models(log=log, force=args.force, check_only=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

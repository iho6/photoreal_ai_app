"""Run: python -m photoreal.portal"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from photoreal.portal.paths import ENV_PATH, LOGS_DIR, REPO_ROOT


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Photoreal launch portal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)

    # Ensure cwd is repo root for relative data paths
    import os

    os.chdir(REPO_ROOT)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH)

    import uvicorn

    from photoreal.portal.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

"""Read/write portal credentials (.env + local git config)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from photoreal.portal.paths import ENV_PATH, REPO_ROOT

_ENV_KEYS = (
    "HF_TOKEN",
    "CIVITAI_API_TOKEN",
    "GITHUB_TOKEN",
    "RUNPOD_API_KEY",
    "FLASH_CHARACTER_ENDPOINT",
    "FLASH_VOLUME_SYNCED",
    "GENERATE_BACKEND",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        out[key] = val
    return out


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    existing = _parse_env_file(path) if path.is_file() else {}
    for k in _ENV_KEYS:
        if k in values:
            existing[k] = values[k] or ""
    lines = [
        "# Managed by photoreal portal — do not commit",
        "",
    ]
    for k in _ENV_KEYS:
        lines.append(f"{k}={existing.get(k, '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_credentials() -> dict[str, Any]:
    env = _parse_env_file(ENV_PATH)
    git_name = _git_config_get("user.name")
    git_email = _git_config_get("user.email")
    # Localhost portal only — return real values so the UI can prefill and reveal.
    return {
        "hf_token_set": bool(env.get("HF_TOKEN")),
        "civitai_token_set": bool(env.get("CIVITAI_API_TOKEN")),
        "github_token_set": bool(env.get("GITHUB_TOKEN")),
        "runpod_token_set": bool(env.get("RUNPOD_API_KEY")),
        "git_user_name": git_name or "",
        "git_user_email": git_email or "",
        "hf_token": env.get("HF_TOKEN") or "",
        "civitai_api_token": env.get("CIVITAI_API_TOKEN") or "",
        "github_token": env.get("GITHUB_TOKEN") or "",
        "runpod_api_key": env.get("RUNPOD_API_KEY") or "",
        "flash_character_endpoint": env.get("FLASH_CHARACTER_ENDPOINT") or "",
        "flash_volume_synced": env.get("FLASH_VOLUME_SYNCED") or "",
        "generate_backend": (env.get("GENERATE_BACKEND") or "auto").strip().lower()
        or "auto",
    }


def save_credentials(
    *,
    hf_token: str | None = None,
    civitai_api_token: str | None = None,
    github_token: str | None = None,
    runpod_api_key: str | None = None,
    flash_character_endpoint: str | None = None,
    flash_volume_synced: str | None = None,
    generate_backend: str | None = None,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
) -> dict[str, Any]:
    current = _parse_env_file(ENV_PATH)
    updates: dict[str, str] = {}

    def _accept(key: str, value: str | None) -> None:
        if value is None:
            return
        v = value.strip()
        if not v or re.fullmatch(r"•+", v):
            return  # keep existing
        updates[key] = v

    _accept("HF_TOKEN", hf_token)
    _accept("CIVITAI_API_TOKEN", civitai_api_token)
    _accept("GITHUB_TOKEN", github_token)
    _accept("RUNPOD_API_KEY", runpod_api_key)
    if flash_character_endpoint is not None:
        updates["FLASH_CHARACTER_ENDPOINT"] = flash_character_endpoint.strip()
    if flash_volume_synced is not None:
        # Allow "" to clear the complete-models flag
        updates["FLASH_VOLUME_SYNCED"] = flash_volume_synced.strip()
    if generate_backend is not None:
        gb = generate_backend.strip().lower() or "auto"
        if gb not in ("auto", "local", "runpod"):
            raise ValueError("GENERATE_BACKEND must be auto, local, or runpod")
        updates["GENERATE_BACKEND"] = gb

    merged = {**current, **updates}
    if not merged.get("HF_TOKEN"):
        raise ValueError("HF_TOKEN is required (accept FLUX NC on Hugging Face first)")
    # Runpod + Flash endpoint are required for Launch (checked in bootstrap /
    # portal UI). Allow partial auto-save of HF before those fields are filled.

    _write_env_file(ENV_PATH, merged)

    if git_user_name is not None and git_user_name.strip():
        _git_config_set("user.name", git_user_name.strip())
    if git_user_email is not None and git_user_email.strip():
        _git_config_set("user.email", git_user_email.strip())

    # Apply into process env for subsequent downloads in this process
    import os

    for k in _ENV_KEYS:
        if merged.get(k):
            os.environ[k] = merged[k]
        if k == "HF_TOKEN" and merged.get(k):
            os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", merged[k])

    return load_credentials()


def apply_env_to_process() -> dict[str, str]:
    """Load portal ``.env`` into os.environ; return the token map."""
    import os

    env = _parse_env_file(ENV_PATH)
    for k in _ENV_KEYS:
        v = env.get(k, "")
        if v:
            os.environ[k] = v
        elif k in os.environ and k in (
            "RUNPOD_API_KEY",
            "FLASH_CHARACTER_ENDPOINT",
            "HF_TOKEN",
        ):
            # Portal .env is source of truth — do not keep stale terminal exports
            # when the portal field was cleared.
            pass
    if env.get("HF_TOKEN"):
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", env["HF_TOKEN"])
    return {k: env.get(k, "") for k in _ENV_KEYS}


def assert_launch_credentials() -> dict[str, str]:
    """Require HF + Runpod API key from portal ``.env`` before Launch."""
    tokens = apply_env_to_process()
    if not tokens.get("HF_TOKEN"):
        raise ValueError("HF_TOKEN missing — enter it on the portal before Launch")
    if not tokens.get("RUNPOD_API_KEY"):
        raise ValueError(
            "RUNPOD_API_KEY missing — enter your Runpod API key on the portal before Launch"
        )
    return tokens


def _git_config_get(key: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "config", "--local", "--get", key],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except FileNotFoundError:
        return None
    return None


def _git_config_set(key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--local", key, value],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

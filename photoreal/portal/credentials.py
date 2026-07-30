"""Read/write portal credentials (.env + local git config)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from photoreal.portal.paths import ENV_PATH, REPO_ROOT

_ENV_KEYS = ("HF_TOKEN", "CIVITAI_API_TOKEN", "GITHUB_TOKEN")


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
    return {
        "hf_token_set": bool(env.get("HF_TOKEN")),
        "civitai_token_set": bool(env.get("CIVITAI_API_TOKEN")),
        "github_token_set": bool(env.get("GITHUB_TOKEN")),
        "git_user_name": git_name or "",
        "git_user_email": git_email or "",
        # Never return raw secrets to the browser — only masked placeholders when set
        "hf_token": "••••••••" if env.get("HF_TOKEN") else "",
        "civitai_api_token": "••••••••" if env.get("CIVITAI_API_TOKEN") else "",
        "github_token": "••••••••" if env.get("GITHUB_TOKEN") else "",
    }


def save_credentials(
    *,
    hf_token: str | None = None,
    civitai_api_token: str | None = None,
    github_token: str | None = None,
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

    merged = {**current, **updates}
    if not merged.get("HF_TOKEN"):
        raise ValueError("HF_TOKEN is required (accept FLUX NC on Hugging Face first)")

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
    """Load .env into os.environ; return the token map (for subprocess env)."""
    import os

    env = _parse_env_file(ENV_PATH)
    for k, v in env.items():
        if v:
            os.environ[k] = v
    if env.get("HF_TOKEN"):
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", env["HF_TOKEN"])
    return {k: env.get(k, "") for k in _ENV_KEYS}


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

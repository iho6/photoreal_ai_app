"""Push portal Runpod/HF tokens into GitHub Actions repository secrets."""

from __future__ import annotations

from base64 import b64encode
from typing import Callable

import httpx

from photoreal.flash.gha_deploy import API, detect_github_repo

LogFn = Callable[[str], None]

SECRETS_TOKEN_MSG = (
    "Could not sync GitHub Actions secrets. "
    "GITHUB_TOKEN needs permission to manage Actions secrets "
    "(classic: repo; fine-grained: Secrets Read/Write + Actions). "
    "See docs/portal.md"
)


def _emit(log: LogFn | None, msg: str) -> None:
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Libsodium sealed-box encrypt for GitHub Actions secrets API."""
    from nacl import encoding, public

    pub = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pub)
    encrypted = sealed.encrypt(secret_value.encode("utf-8"))
    return b64encode(encrypted).decode("utf-8")


def sync_actions_secrets(
    *,
    github_token: str,
    runpod_api_key: str,
    hf_token: str = "",
    log: LogFn | None = None,
    client: httpx.Client | None = None,
    owner: str | None = None,
    repo: str | None = None,
) -> None:
    """
    Create/update repo Actions secrets ``RUNPOD_API_KEY`` and optional ``HF_TOKEN``.

    No-op if ``github_token`` or ``runpod_api_key`` is empty.
    """
    token = (github_token or "").strip()
    runpod = (runpod_api_key or "").strip()
    hf = (hf_token or "").strip()
    if not token or not runpod:
        return

    if not owner or not repo:
        owner, repo = detect_github_repo()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "photoreal-flash-secrets",
    }
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(60.0))
    try:
        pk = http.get(
            f"{API}/repos/{owner}/{repo}/actions/secrets/public-key",
            headers=headers,
        )
        if pk.status_code in (401, 403):
            raise RuntimeError(
                f"GitHub secrets public-key forbidden HTTP {pk.status_code}. "
                f"{SECRETS_TOKEN_MSG}"
            )
        if pk.status_code >= 400:
            raise RuntimeError(
                f"GitHub secrets public-key failed HTTP {pk.status_code}: {pk.text[:400]}"
            )
        body = pk.json()
        key_id = str(body.get("key_id") or "")
        key = str(body.get("key") or "")
        if not key_id or not key:
            raise RuntimeError(f"GitHub public-key response incomplete: {body!r}")

        secrets: dict[str, str] = {"RUNPOD_API_KEY": runpod}
        if hf:
            secrets["HF_TOKEN"] = hf

        for name, value in secrets.items():
            encrypted = encrypt_secret(key, value)
            put = http.put(
                f"{API}/repos/{owner}/{repo}/actions/secrets/{name}",
                headers=headers,
                json={"encrypted_value": encrypted, "key_id": key_id},
            )
            if put.status_code in (401, 403):
                raise RuntimeError(
                    f"GitHub put secret {name!r} forbidden HTTP {put.status_code}. "
                    f"{SECRETS_TOKEN_MSG}"
                )
            if put.status_code not in (201, 204):
                raise RuntimeError(
                    f"GitHub put secret {name!r} failed HTTP {put.status_code}: "
                    f"{put.text[:400]}"
                )
            _emit(log, f"flash: synced Actions secret {name}")
        _emit(log, f"flash: Actions secrets OK on {owner}/{repo}")
    finally:
        if owns:
            http.close()


def try_sync_actions_secrets_from_portal(*, log: LogFn | None = None) -> str | None:
    """
    Best-effort sync from portal ``.env``. Returns error message or None on success/skip.
    """
    from photoreal.portal.credentials import apply_env_to_process, load_credentials

    apply_env_to_process()
    creds = load_credentials()
    gh = (creds.get("github_token") or "").strip()
    rp = (creds.get("runpod_api_key") or "").strip()
    if not gh or not rp:
        return None
    try:
        sync_actions_secrets(
            github_token=gh,
            runpod_api_key=rp,
            hf_token=(creds.get("hf_token") or "").strip(),
            log=log,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        _emit(log, f"flash: Actions secrets sync warning: {msg}")
        return msg

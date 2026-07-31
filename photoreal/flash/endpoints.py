"""Resolve Runpod serverless endpoint ids by Flash endpoint name."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

# Must match @Endpoint(name=...) in scripts/flash_character_endpoint.py
CHARACTER_ENDPOINT_NAME = "photoreal-character-4090"

ENDPOINTS_URL = "https://rest.runpod.io/v1/endpoints"

LogFn = Callable[[str], None]


class EndpointNotFoundError(RuntimeError):
    """No serverless endpoint with the expected Flash name exists yet."""


def resolve_character_endpoint_id(
    api_key: str,
    *,
    preferred_id: str | None = None,
    name: str = CHARACTER_ENDPOINT_NAME,
    log: LogFn | None = None,
    client: httpx.Client | None = None,
) -> str:
    """
    Return the serverless endpoint id for the character Flash worker.

    If ``preferred_id`` is set (portal cache / override), return it immediately.
    Otherwise list account endpoints and match ``name``.
    """
    preferred = (preferred_id or "").strip()
    if preferred:
        if log:
            log(f"flash: using endpoint id from .env ({preferred})")
        return preferred

    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("Runpod API key is required to resolve the Flash endpoint id")

    if log:
        log(f"flash: resolving endpoint id for name={name!r}…")

    headers = {"Authorization": f"Bearer {key}"}
    owns_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        resp = http.get(ENDPOINTS_URL, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Runpod list endpoints failed HTTP {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
    finally:
        if owns_client:
            http.close()

    items = _normalize_endpoint_list(data)
    matches = [ep for ep in items if str(ep.get("name") or "") == name]
    if not matches:
        raise EndpointNotFoundError(
            f"No Runpod endpoint named {name!r}. "
            "Deploy with .\\scripts\\flash_deploy_character.ps1 (WSL) or retry Generate "
            "to auto-deploy."
        )

    chosen = _pick_newest(matches)
    eid = str(chosen.get("id") or "").strip()
    if not eid:
        raise RuntimeError(f"Matched endpoint {name!r} but response had no id: {chosen!r}")

    if log:
        extra = f" ({len(matches)} matches, picked newest)" if len(matches) > 1 else ""
        log(f"flash: resolved {name!r} -> {eid}{extra}")
    return eid


def ensure_character_endpoint_id(
    api_key: str,
    *,
    preferred_id: str | None = None,
    log: LogFn | None = None,
    auto_deploy: bool = True,
) -> str:
    """Resolve endpoint id; optionally Flash-deploy when missing, then resolve again."""
    try:
        return resolve_character_endpoint_id(
            api_key,
            preferred_id=preferred_id,
            log=log,
        )
    except EndpointNotFoundError:
        if preferred_id and preferred_id.strip():
            raise
        if not auto_deploy:
            raise
        if log:
            log("flash: endpoint missing — deploying via Flash CLI (WSL on Windows)…")
        from photoreal.flash.deploy import deploy_character_endpoint

        deploy_character_endpoint(log=log)
        last_err: Exception | None = None
        for attempt in range(1, 7):
            time.sleep(2 * attempt)
            try:
                return resolve_character_endpoint_id(
                    api_key, preferred_id=None, log=log
                )
            except EndpointNotFoundError as exc:
                last_err = exc
                if log:
                    log(f"flash: waiting for endpoint to appear (try {attempt}/6)…")
        raise RuntimeError(
            f"Deploy finished but endpoint {CHARACTER_ENDPOINT_NAME!r} still not listed. "
            "Run .\\scripts\\flash_deploy_character.ps1 manually, confirm in Runpod console, "
            "then retry Generate. Also sync Network Volume photoreal-models (docs/portal.md)."
        ) from last_err


def _normalize_endpoint_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("endpoints", "data", "items"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _pick_newest(matches: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(ep: dict[str, Any]) -> str:
        return str(ep.get("createdAt") or ep.get("created_at") or "")

    return max(matches, key=sort_key)

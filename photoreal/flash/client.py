"""Call Runpod Serverless HTTP from the Windows portal (no Flash CLI)."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from photoreal.flash.endpoints import (
    CHARACTER_ENDPOINT_NAME,
    ensure_character_endpoint_id,
)
from photoreal.portal.credentials import (
    apply_env_to_process,
    load_credentials,
    save_credentials,
)

LogFn = Callable[[str], None]


def _emit(log: LogFn | None, msg: str) -> None:
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def run_character_via_runpod(
    prompt: str,
    *,
    output_dir: Path,
    log: LogFn | None = None,
    poll_interval_s: float = 2.0,
    max_wait_s: float = 900.0,
) -> dict[str, Any]:
    """
    Submit character generate via /run + /status.

    Endpoint id comes from ``FLASH_CHARACTER_ENDPOINT`` if set, else auto-resolved
    by name ``photoreal-character-4090`` using the Runpod API key.

    Returns {rewritten, images: [{path, name}], logs: [...]} after writing PNGs
    into output_dir.
    """
    apply_env_to_process()
    creds = load_credentials()
    api_key = (creds.get("runpod_api_key") or "").strip()
    cached_id = (creds.get("flash_character_endpoint") or "").strip()
    if not api_key:
        raise RuntimeError("RUNPOD_API_KEY is not set (save it on the portal login page)")

    had_cache = bool(cached_id)
    endpoint_id = ensure_character_endpoint_id(
        api_key,
        preferred_id=cached_id or None,
        log=lambda msg: _emit(log, msg),
        auto_deploy=True,
    )
    if not had_cache:
        try:
            save_credentials(flash_character_endpoint=endpoint_id)
            _emit(log, f"flash: cached endpoint id in .env ({endpoint_id})")
        except Exception as exc:  # noqa: BLE001
            _emit(log, f"flash: could not cache endpoint id ({exc})")

    from photoreal.flash.volume_sync import ensure_volume_models_ready

    ensure_volume_models_ready(log=lambda msg: _emit(log, msg))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base = f"https://api.runpod.ai/v2/{endpoint_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"input": {"prompt": prompt}}

    src = "from .env" if had_cache else f"resolved from name={CHARACTER_ENDPOINT_NAME}"
    _emit(log, f"backend=runpod endpoint={endpoint_id} ({src})")
    _emit(log, "runpod: submitting job (/run) — cold start may take minutes…")

    with httpx.Client(timeout=httpx.Timeout(60.0, read=120.0)) as client:
        submit = client.post(f"{base}/run", headers=headers, json=payload)
        if submit.status_code >= 400:
            raise RuntimeError(
                f"Runpod /run failed HTTP {submit.status_code}: {submit.text[:800]}"
            )
        body = submit.json()
        job_id = body.get("id") or body.get("jobId")
        if not job_id:
            raise RuntimeError(f"Runpod /run missing job id: {body!r}")

        _emit(log, f"runpod: job_id={job_id}")

        deadline = time.time() + max_wait_s
        last_status = ""
        while time.time() < deadline:
            st = client.get(f"{base}/status/{job_id}", headers=headers)
            if st.status_code >= 400:
                raise RuntimeError(
                    f"Runpod /status failed HTTP {st.status_code}: {st.text[:800]}"
                )
            data = st.json()
            status = str(data.get("status") or "").upper()
            if status != last_status:
                _emit(log, f"runpod: status={status}")
                last_status = status

            if status == "COMPLETED":
                output = data.get("output")
                if isinstance(output, list) and output:
                    # Some workers wrap as [{…}]
                    output = output[0] if isinstance(output[0], dict) else {"raw": output}
                if not isinstance(output, dict):
                    output = {"raw": output}
                return _ingest_output(output, output_dir=output_dir, log=log)

            if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                err = data.get("error") or data.get("output") or data
                raise RuntimeError(f"Runpod job {status}: {err!r}")

            time.sleep(poll_interval_s)

    raise RuntimeError(f"Runpod job {job_id} timed out after {max_wait_s:.0f}s")


def _ingest_output(
    output: dict[str, Any],
    *,
    output_dir: Path,
    log: LogFn | None,
) -> dict[str, Any]:
    for line in output.get("logs") or []:
        _emit(log, f"remote: {line}")

    rewritten = output.get("rewritten")
    if rewritten:
        _emit(log, f"runpod: rewritten = {str(rewritten)[:400]!r}")

    images: list[dict[str, Any]] = []
    for i, item in enumerate(output.get("images_b64") or []):
        if isinstance(item, dict):
            b64 = item.get("b64") or item.get("data") or ""
            name = item.get("name") or f"runpod_{i:03d}.png"
        else:
            b64 = str(item)
            name = f"runpod_{i:03d}.png"
        if not b64:
            continue
        # Allow data-url prefix
        if "," in b64 and b64.strip().startswith("data:"):
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        safe = Path(name).name
        if not safe.lower().endswith(".png"):
            safe = f"{safe}.png"
        path = output_dir / safe
        # Avoid clobber: unique suffix if exists
        if path.exists():
            stem = path.stem
            path = output_dir / f"{stem}_{int(time.time())}.png"
        path.write_bytes(raw)
        images.append({"path": path, "name": path.name})
        _emit(log, f"runpod: wrote {path.name} ({len(raw)} bytes)")

    if output.get("error"):
        raise RuntimeError(str(output["error"]))
    if not images and not rewritten:
        raise RuntimeError(f"Runpod output empty: {output!r}")

    return {
        "rewritten": rewritten,
        "images": images,
        "logs": list(output.get("logs") or []),
    }

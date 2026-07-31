"""Ensure Network Volume photoreal-models has complete character models (via Runpod pod)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from photoreal.flash.volume_layout import (
    READY_MARKER,
    VOLUME_DATACENTER,
    VOLUME_NAME,
    VOLUME_SIZE_GB,
    volume_missing_parts,
    volume_models_complete,
)
from photoreal.portal.credentials import (
    apply_env_to_process,
    load_credentials,
    save_credentials,
)
from photoreal.portal.paths import REPO_ROOT

LogFn = Callable[[str], None]

VOLUMES_URL = "https://rest.runpod.io/v1/networkvolumes"
PODS_URL = "https://rest.runpod.io/v1/pods"

BOOTSTRAP = REPO_ROOT / "scripts" / "flash_volume_bootstrap.sh"
DOWNLOAD_PY = REPO_ROOT / "scripts" / "download_models.py"
YAML_PATH = REPO_ROOT / "scripts" / "flash_comfyui_extra_model_paths.yaml"
LAYOUT_PY = REPO_ROOT / "photoreal" / "flash" / "volume_layout.py"

# CPU image with Python + git; volume attaches at /workspace on pods.
POD_IMAGE = "runpod/base:0.6.2-ubuntu2204-jammy"


def _emit(log: LogFn | None, msg: str) -> None:
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def volume_sync_flag_set(creds: dict[str, Any] | None = None) -> bool:
    c = creds if creds is not None else load_credentials()
    return str(c.get("flash_volume_synced") or "").strip() in ("1", "true", "yes")


def volume_sync_needed(*, force: bool = False) -> bool:
    """True if Generate should run a volume ensure/sync pod."""
    if force:
        return True
    apply_env_to_process()
    return not volume_sync_flag_set()


def ensure_network_volume_id(
    api_key: str,
    *,
    client: httpx.Client | None = None,
    log: LogFn | None = None,
) -> str:
    """Return id for volume ``photoreal-models`` in US-GA-2 (create if missing)."""
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("RUNPOD_API_KEY required to ensure Network Volume")
    headers = {"Authorization": f"Bearer {key}"}
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(60.0))
    try:
        resp = http.get(VOLUMES_URL, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"List network volumes failed HTTP {resp.status_code}: {resp.text[:500]}"
            )
        items = _as_list(resp.json())
        named = [v for v in items if str(v.get("name") or "") == VOLUME_NAME]
        exact = [
            v
            for v in named
            if str(v.get("dataCenterId") or "") == VOLUME_DATACENTER
        ]
        chosen = exact[0] if exact else (named[0] if named else None)
        if chosen is not None:
            vid = str(chosen.get("id") or "").strip()
            if vid:
                dc = str(chosen.get("dataCenterId") or "")
                if dc and dc != VOLUME_DATACENTER:
                    _emit(
                        log,
                        f"flash: warning volume {VOLUME_NAME!r} is in {dc}, "
                        f"endpoint expects {VOLUME_DATACENTER}",
                    )
                _emit(log, f"flash: volume {VOLUME_NAME!r} id={vid}")
                return vid

        _emit(log, f"flash: creating network volume {VOLUME_NAME!r} @ {VOLUME_DATACENTER}…")
        create = http.post(
            VOLUMES_URL,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "name": VOLUME_NAME,
                "size": VOLUME_SIZE_GB,
                "dataCenterId": VOLUME_DATACENTER,
            },
        )
        if create.status_code >= 400:
            raise RuntimeError(
                f"Create network volume failed HTTP {create.status_code}: {create.text[:800]}"
            )
        body = create.json()
        vid = str(body.get("id") or "").strip()
        if not vid:
            raise RuntimeError(f"Create volume response missing id: {body!r}")
        _emit(log, f"flash: created volume id={vid}")
        return vid
    finally:
        if owns:
            http.close()


def sync_volume_models(
    *,
    log: LogFn | None = None,
    force: bool = False,
    timeout_s: float = 14_400.0,
    check_only: bool = False,
) -> None:
    """
    Ensure volume models are **complete** (file size / layout checks).

    Spins a short-lived Secure Cloud pod attached to ``photoreal-models``.
    Skips when ``FLASH_VOLUME_SYNCED=1`` unless ``force`` or ``check_only``.
    Sets ``FLASH_VOLUME_SYNCED=1`` only after completeness is confirmed.
    """
    apply_env_to_process()
    creds = load_credentials()
    api_key = (creds.get("runpod_api_key") or "").strip()
    hf = (creds.get("hf_token") or "").strip()
    if not api_key:
        raise RuntimeError("RUNPOD_API_KEY missing — save it on the portal before volume sync")
    if not check_only and not hf:
        raise RuntimeError(
            "HF_TOKEN missing — required to download gated FLUX / VLM weights onto the volume"
        )

    if not force and not check_only and volume_sync_flag_set(creds):
        _emit(
            log,
            "flash: volume sync skipped "
            "(FLASH_VOLUME_SYNCED=1; models previously verified complete)",
        )
        return

    with httpx.Client(timeout=httpx.Timeout(60.0, read=120.0)) as http:
        volume_id = ensure_network_volume_id(api_key, client=http, log=log)
        # check_only → completeness probe only; force → re-download gaps; else fill if incomplete
        start_script = _build_pod_start_script(
            force=force and not check_only,
            check_only=check_only,
        )

        _emit(
            log,
            "flash: starting volume sync/check pod "
            "(downloads only if incomplete; may take hours)…",
        )
        pod_id = _create_sync_pod(
            http,
            api_key=api_key,
            volume_id=volume_id,
            hf_token=hf,
            civitai=(creds.get("civitai_api_token") or "").strip(),
            start_script=start_script,
            force=force and not check_only,
            check_only=check_only,
            log=log,
        )
        _emit(log, f"flash: volume pod id={pod_id}")
        try:
            ok = _wait_pod_signal(
                http,
                api_key=api_key,
                pod_id=pod_id,
                timeout_s=timeout_s if not check_only else min(timeout_s, 1800.0),
                log=log,
            )
            if not ok:
                # Confirm via a second short check pod (completeness only)
                _emit(log, "flash: verifying volume completeness with check pod…")
                ok = _run_check_pod(
                    http,
                    api_key=api_key,
                    volume_id=volume_id,
                    timeout_s=min(timeout_s, 1800.0),
                    log=log,
                )
            if not ok:
                save_credentials(flash_volume_synced="")
                raise RuntimeError(
                    "Network Volume models are incomplete after sync/check. "
                    "See pod logs in the Runpod console, ensure HF_TOKEN can access "
                    "FLUX NC + Qwen, then retry: python scripts/flash_sync_volume.py --force"
                )
            save_credentials(flash_volume_synced="1")
            _emit(log, "flash: volume models verified complete; FLASH_VOLUME_SYNCED=1")
        finally:
            _terminate_pod(http, api_key=api_key, pod_id=pod_id, log=log)


def ensure_volume_models_ready(*, log: LogFn | None = None, force: bool = False) -> None:
    """Called from Generate — sync only when flag missing or force."""
    if volume_sync_needed(force=force):
        _emit(log, "flash: Network Volume not marked complete — syncing/checking models…")
        sync_volume_models(log=log, force=force, check_only=False)


def _as_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("networkVolumes", "items", "data"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _build_pod_start_script(*, force: bool, check_only: bool) -> str:
    """Assemble bash that materializes payload then runs bootstrap or check-only."""
    for path in (BOOTSTRAP, DOWNLOAD_PY, YAML_PATH, LAYOUT_PY):
        if not path.is_file():
            raise RuntimeError(f"Missing sync asset: {path}")

    parts = {
        "bootstrap.sh": _b64(BOOTSTRAP),
        "download_models.py": _b64(DOWNLOAD_PY),
        "flash_comfyui_extra_model_paths.yaml": _b64(YAML_PATH),
        "volume_layout.py": _b64(LAYOUT_PY),
    }
    force_s = "1" if force else "0"
    decode_lines = [
        "set -euo pipefail",
        "PAYLOAD=/tmp/photoreal_sync_payload",
        "mkdir -p \"$PAYLOAD\"",
    ]
    for name, b64 in parts.items():
        decode_lines.append(f"echo '{b64}' | base64 -d > \"$PAYLOAD/{name}\"")
    decode_lines.append("chmod +x \"$PAYLOAD/bootstrap.sh\"")
    decode_lines.append("export PHOTOREAL_SYNC_PAYLOAD=\"$PAYLOAD\"")
    decode_lines.append(f"export PHOTOREAL_FORCE_SYNC={force_s}")
    if check_only:
        decode_lines.extend(
            [
                "export PHOTOREAL_VOLUME_ROOT=${PHOTOREAL_VOLUME_ROOT:-/workspace}",
                "if [[ ! -d $PHOTOREAL_VOLUME_ROOT ]]; then "
                "if [[ -d /runpod-volume ]]; then export PHOTOREAL_VOLUME_ROOT=/runpod-volume; "
                "else export PHOTOREAL_VOLUME_ROOT=/workspace; fi; fi",
                "python3 - <<'PY'",
                "import os, sys",
                "sys.path.insert(0, os.environ['PHOTOREAL_SYNC_PAYLOAD'])",
                "from volume_layout import volume_missing_parts",
                "from pathlib import Path",
                "root = Path(os.environ['PHOTOREAL_VOLUME_ROOT'])",
                "missing = volume_missing_parts(root)",
                "if missing:",
                "    print('INCOMPLETE:')",
                "    [print('  -', m) for m in missing]",
                "    print('PHOTOREAL_VOLUME_SYNC_FAIL incomplete')",
                "    sys.exit(1)",
                "print('COMPLETE')",
                "print('PHOTOREAL_VOLUME_SYNC_OK already_complete')",
                "Path(root, '.photoreal_volume_ready').touch()",
                "sys.exit(0)",
                "PY",
            ]
        )
    else:
        decode_lines.append("bash \"$PAYLOAD/bootstrap.sh\"")
    return "\n".join(decode_lines)


def _create_sync_pod(
    http: httpx.Client,
    *,
    api_key: str,
    volume_id: str,
    hf_token: str,
    civitai: str,
    start_script: str,
    force: bool,
    check_only: bool,
    log: LogFn | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # Keep start script under control: write via env file in command
    # dockerStartCmd runs bash -lc with script from base64 env to avoid huge JSON issues
    script_b64 = base64.b64encode(start_script.encode("utf-8")).decode("ascii")
    # Chunk if needed — Runpod env value limits; script can be large due to download_models
    # Prefer writing script from multiple env parts
    chunks = [script_b64[i : i + 8_000] for i in range(0, len(script_b64), 8_000)]
    env = {
        "HF_TOKEN": hf_token,
        "HUGGING_FACE_HUB_TOKEN": hf_token,
        "CIVITAI_API_TOKEN": civitai,
        "PHOTOREAL_FORCE_SYNC": "1" if force else "0",
        "PHOTOREAL_SYNC_CHUNKS": str(len(chunks)),
    }
    for i, ch in enumerate(chunks):
        env[f"PHOTOREAL_SYNC_B64_{i}"] = ch

    wrapper = (
        "set -euo pipefail; "
        "python3 - <<'PY'\n"
        "import os, base64\n"
        "n = int(os.environ.get('PHOTOREAL_SYNC_CHUNKS', '0'))\n"
        "data = ''.join(os.environ.get(f'PHOTOREAL_SYNC_B64_{i}', '') for i in range(n))\n"
        "open('/tmp/photoreal_sync_start.sh', 'wb').write(base64.b64decode(data))\n"
        "PY\n"
        "bash /tmp/photoreal_sync_start.sh"
    )

    name = "photoreal-vol-check" if check_only else "photoreal-vol-sync"
    body: dict[str, Any] = {
        "name": name,
        "imageName": POD_IMAGE,
        "cloudType": "SECURE",
        "computeType": "CPU",
        "dataCenterIds": [VOLUME_DATACENTER],
        "vcpuCount": 4,
        "containerDiskInGb": 30,
        "networkVolumeId": volume_id,
        "ports": ["22/tcp"],
        "env": env,
        "dockerStartCmd": ["bash", "-lc", wrapper],
    }
    resp = http.post(PODS_URL, headers=headers, json=body)
    if resp.status_code >= 400:
        # Fallback: GPU if CPU+volume rejected in this datacenter
        _emit(
            log,
            f"CPU pod create failed ({resp.status_code}); retrying with GPU…",
        )
        body.pop("computeType", None)
        body.pop("vcpuCount", None)
        body["gpuTypeIds"] = [
            "NVIDIA GeForce RTX 4090",
            "NVIDIA RTX A5000",
            "NVIDIA A40",
        ]
        body["gpuCount"] = 1
        resp = http.post(PODS_URL, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Create sync pod failed HTTP {resp.status_code}: {resp.text[:1000]}"
            )
    data = resp.json()
    pod_id = str(data.get("id") or "").strip()
    if not pod_id:
        raise RuntimeError(f"Create pod missing id: {data!r}")
    return pod_id


def _wait_pod_signal(
    http: httpx.Client,
    *,
    api_key: str,
    pod_id: str,
    timeout_s: float,
    log: LogFn | None,
) -> bool:
    """Return True if PHOTOREAL_VOLUME_SYNC_OK seen in logs or inferred."""
    deadline = time.time() + timeout_s
    headers = {"Authorization": f"Bearer {api_key}"}
    saw_fail = False
    last_status = ""
    while time.time() < deadline:
        st = http.get(f"{PODS_URL}/{pod_id}", headers=headers)
        if st.status_code < 400:
            info = st.json()
            status = str(
                info.get("desiredStatus")
                or info.get("lastStatus")
                or info.get("status")
                or ""
            ).upper()
            if status and status != last_status:
                _emit(log, f"flash: volume pod status={status}")
                last_status = status
            if status in ("EXITED", "DEAD", "TERMINATED"):
                break

        # Best-effort log scrape (v2 SSE / snapshot)
        text = _fetch_pod_logs_snapshot(http, api_key=api_key, pod_id=pod_id)
        if text:
            if "PHOTOREAL_VOLUME_SYNC_OK" in text:
                _emit(log, "flash: saw PHOTOREAL_VOLUME_SYNC_OK in pod logs")
                return True
            if "PHOTOREAL_VOLUME_SYNC_FAIL" in text:
                saw_fail = True
                _emit(log, "flash: saw PHOTOREAL_VOLUME_SYNC_FAIL in pod logs")
                break
        time.sleep(15.0)

    if saw_fail:
        return False
    # Pod finished without log signal — caller may verify with check pod
    return False


def _fetch_pod_logs_snapshot(
    http: httpx.Client, *, api_key: str, pod_id: str
) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    urls = (
        f"https://rest.runpod.io/v2/pods/{pod_id}/logs",
        f"https://rest.runpod.io/v1/pods/{pod_id}/logs",
    )
    chunks: list[str] = []
    for url in urls:
        try:
            with http.stream("GET", url, headers=headers, timeout=20.0) as resp:
                if resp.status_code >= 400:
                    continue
                n = 0
                for line in resp.iter_lines():
                    if line:
                        chunks.append(line)
                    n += 1
                    if n > 500:
                        break
            if chunks:
                return "\n".join(chunks)
        except Exception:  # noqa: BLE001
            continue
    return ""


def _run_check_pod(
    http: httpx.Client,
    *,
    api_key: str,
    volume_id: str,
    timeout_s: float,
    log: LogFn | None,
) -> bool:
    script = _build_pod_start_script(force=False, check_only=True)
    pod_id = _create_sync_pod(
        http,
        api_key=api_key,
        volume_id=volume_id,
        hf_token="",
        civitai="",
        start_script=script,
        force=False,
        check_only=True,
        log=log,
    )
    _emit(log, f"flash: check pod id={pod_id}")
    try:
        return _wait_pod_signal(
            http, api_key=api_key, pod_id=pod_id, timeout_s=timeout_s, log=log
        )
    finally:
        _terminate_pod(http, api_key=api_key, pod_id=pod_id, log=log)


def _terminate_pod(
    http: httpx.Client, *, api_key: str, pod_id: str, log: LogFn | None
) -> None:
    try:
        http.delete(
            f"{PODS_URL}/{pod_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        _emit(log, f"flash: terminated volume pod {pod_id}")
    except Exception as exc:  # noqa: BLE001
        _emit(log, f"flash: could not terminate pod {pod_id} ({exc})")


# Re-export layout helpers for tests / CLI
__all__ = [
    "READY_MARKER",
    "VOLUME_DATACENTER",
    "VOLUME_NAME",
    "ensure_network_volume_id",
    "ensure_volume_models_ready",
    "sync_volume_models",
    "volume_missing_parts",
    "volume_models_complete",
    "volume_sync_flag_set",
    "volume_sync_needed",
]

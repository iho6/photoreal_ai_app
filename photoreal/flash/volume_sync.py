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

# CPU image with Python + git (must be a real Hub tag — jammy suffix does not exist).
# Volume attaches at volumeMountPath (/workspace).
POD_IMAGE = "runpod/base:1.0.7-ubuntu2204"


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


def ensure_network_volume(
    api_key: str,
    *,
    client: httpx.Client | None = None,
    log: LogFn | None = None,
) -> tuple[str, str]:
    """
    Return ``(volume_id, data_center_id)`` for ``photoreal-models`` in
    ``VOLUME_DATACENTER`` (create if missing).

    Never reuses a same-named volume in a different datacenter — that causes
    sync pods scheduled in the wrong DC and empty mounts.
    """
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
        if exact:
            chosen = exact[0]
            vid = str(chosen.get("id") or "").strip()
            dc = str(chosen.get("dataCenterId") or VOLUME_DATACENTER).strip()
            if not vid:
                raise RuntimeError(f"Volume {VOLUME_NAME!r} matched but has no id")
            _emit(log, f"flash: volume {VOLUME_NAME!r} id={vid} dc={dc}")
            return vid, dc

        wrong = [
            v
            for v in named
            if str(v.get("dataCenterId") or "") != VOLUME_DATACENTER
        ]
        if wrong:
            details = ", ".join(
                f"id={v.get('id')} dc={v.get('dataCenterId')}" for v in wrong[:5]
            )
            _emit(
                log,
                f"flash: ignoring {len(wrong)} {VOLUME_NAME!r} volume(s) outside "
                f"{VOLUME_DATACENTER} ({details}); creating one in {VOLUME_DATACENTER}",
            )

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
        dc = str(body.get("dataCenterId") or VOLUME_DATACENTER).strip()
        if not vid:
            raise RuntimeError(f"Create volume response missing id: {body!r}")
        _emit(log, f"flash: created volume id={vid} dc={dc}")
        return vid, dc
    finally:
        if owns:
            http.close()


def ensure_network_volume_id(
    api_key: str,
    *,
    client: httpx.Client | None = None,
    log: LogFn | None = None,
) -> str:
    """Return volume id only (compat wrapper). Prefer ``ensure_network_volume``."""
    vid, _dc = ensure_network_volume(api_key, client=client, log=log)
    return vid


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
        volume_id, volume_dc = ensure_network_volume(api_key, client=http, log=log)
        # Assets are chunked into pod env inside _create_sync_pod
        _emit(
            log,
            "flash: starting volume sync/check pod "
            f"@ {volume_dc} "
            "(downloads only if incomplete; may take hours)…",
        )
        pod_id = _create_sync_pod(
            http,
            api_key=api_key,
            volume_id=volume_id,
            volume_dc=volume_dc,
            hf_token=hf,
            civitai=(creds.get("civitai_api_token") or "").strip(),
            force=force and not check_only,
            check_only=check_only,
            log=log,
        )
        _emit(log, f"flash: volume pod id={pod_id}")
        last_logs = ""
        try:
            ok, last_logs = _wait_pod_signal(
                http,
                api_key=api_key,
                pod_id=pod_id,
                timeout_s=timeout_s if not check_only else min(timeout_s, 1800.0),
                log=log,
            )
            if not ok:
                if check_only:
                    # Already ran a completeness-only pod; no need for a second one.
                    pass
                else:
                    # Confirm via a second short check pod (completeness only)
                    _emit(log, "flash: verifying volume completeness with check pod…")
                    ok, check_logs = _run_check_pod(
                        http,
                        api_key=api_key,
                        volume_id=volume_id,
                        volume_dc=volume_dc,
                        timeout_s=min(timeout_s, 1800.0),
                        log=log,
                    )
                    if check_logs:
                        last_logs = check_logs
            if not ok:
                save_credentials(flash_volume_synced="")
                tail = _log_tail(last_logs, max_lines=40)
                extra = f"\nPod log tail:\n{tail}" if tail else ""
                raise RuntimeError(
                    "Network Volume models are incomplete after sync/check. "
                    "Restart the portal after Flash datacenter changes so "
                    f"VOLUME_DATACENTER={VOLUME_DATACENTER} is loaded. "
                    "First fill can take hours. "
                    "See pod logs in the Runpod console, ensure HF_TOKEN can access "
                    "FLUX NC + Qwen, then retry: python scripts/flash_sync_volume.py --force"
                    f"{extra}"
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
    # Pods run Linux bash — strip Windows CRLF so `set -o pipefail` etc. work.
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return base64.b64encode(data).decode("ascii")


def _chunk_env(prefix: str, data: str, env: dict[str, str], *, size: int = 8_000) -> None:
    chunks = [data[i : i + size] for i in range(0, len(data), size)] or [""]
    env[f"{prefix}_N"] = str(len(chunks))
    for i, ch in enumerate(chunks):
        env[f"{prefix}_{i}"] = ch


def _build_check_only_script() -> str:
    """Small inline completeness check (no download_models embed)."""
    return "\n".join(
        [
            "set -euo pipefail",
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
            "    print('INCOMPLETE:', flush=True)",
            "    [print('  -', m, flush=True) for m in missing]",
            "    print('PHOTOREAL_VOLUME_SYNC_FAIL incomplete', flush=True)",
            "    sys.exit(1)",
            "print('COMPLETE', flush=True)",
            "print('PHOTOREAL_VOLUME_SYNC_OK already_complete', flush=True)",
            "Path(root, '.photoreal_volume_ready').touch()",
            "sys.exit(0)",
            "PY",
        ]
    )


def _log_tail(text: str, *, max_lines: int = 40) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _create_sync_pod(
    http: httpx.Client,
    *,
    api_key: str,
    volume_id: str,
    volume_dc: str,
    hf_token: str,
    civitai: str,
    force: bool,
    check_only: bool,
    log: LogFn | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for path in (BOOTSTRAP, DOWNLOAD_PY, YAML_PATH, LAYOUT_PY):
        if not path.is_file():
            raise RuntimeError(f"Missing sync asset: {path}")

    env: dict[str, str] = {
        "HF_TOKEN": hf_token,
        "HUGGING_FACE_HUB_TOKEN": hf_token,
        "CIVITAI_API_TOKEN": civitai,
        "PHOTOREAL_FORCE_SYNC": "1" if force else "0",
        "PHOTOREAL_CHECK_ONLY": "1" if check_only else "0",
        "PYTHONUNBUFFERED": "1",
        "PHOTOREAL_VOLUME_ROOT": "/workspace",
    }
    # Decode assets from env on the pod (avoids giant echo|base64 lines in a script).
    _chunk_env("PHOTOREAL_F_bootstrap_sh", _b64(BOOTSTRAP), env)
    _chunk_env("PHOTOREAL_F_download_models_py", _b64(DOWNLOAD_PY), env)
    _chunk_env("PHOTOREAL_F_extra_yaml", _b64(YAML_PATH), env)
    _chunk_env("PHOTOREAL_F_volume_layout_py", _b64(LAYOUT_PY), env)
    if check_only:
        _chunk_env(
            "PHOTOREAL_F_check_sh",
            base64.b64encode(_build_check_only_script().encode("utf-8")).decode("ascii"),
            env,
        )

    # Line-buffered stdout + heartbeat on the volume (SSE logs often stay empty
    # while bash fully-buffers a long-running non-TTY process).
    wrapper = r"""
set -euo pipefail
VOL="${PHOTOREAL_VOLUME_ROOT:-/workspace}"
mkdir -p "$VOL" /tmp/photoreal_sync_payload
echo "photoreal-vol-sync: starting $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$VOL/photoreal_sync.log"
echo "photoreal-vol-sync: python=$(command -v python3 || echo missing)" | tee -a "$VOL/photoreal_sync.log"
decode_asset() {
  local prefix="$1" out="$2"
  local n_var="${prefix}_N"
  local n="${!n_var}"
  local i=0 varname
  : > /tmp/_photoreal_asset.b64
  while [ "$i" -lt "$n" ]; do
    varname="${prefix}_$i"
    printf '%s' "${!varname}" >> /tmp/_photoreal_asset.b64
    i=$((i+1))
  done
  base64 -d /tmp/_photoreal_asset.b64 > "$out"
}
PAYLOAD=/tmp/photoreal_sync_payload
decode_asset PHOTOREAL_F_bootstrap_sh "$PAYLOAD/bootstrap.sh"
decode_asset PHOTOREAL_F_download_models_py "$PAYLOAD/download_models.py"
decode_asset PHOTOREAL_F_extra_yaml "$PAYLOAD/flash_comfyui_extra_model_paths.yaml"
decode_asset PHOTOREAL_F_volume_layout_py "$PAYLOAD/volume_layout.py"
chmod +x "$PAYLOAD/bootstrap.sh"
export PHOTOREAL_SYNC_PAYLOAD="$PAYLOAD"
export PHOTOREAL_FORCE_SYNC="${PHOTOREAL_FORCE_SYNC:-0}"
echo "photoreal-vol-sync: assets ready check_only=${PHOTOREAL_CHECK_ONLY:-0}" | tee -a "$VOL/photoreal_sync.log"
if [ "${PHOTOREAL_CHECK_ONLY:-0}" = "1" ]; then
  decode_asset PHOTOREAL_F_check_sh /tmp/photoreal_check.sh
  chmod +x /tmp/photoreal_check.sh
  if command -v stdbuf >/dev/null 2>&1; then
    exec stdbuf -oL -eL bash /tmp/photoreal_check.sh
  fi
  exec bash /tmp/photoreal_check.sh
fi
if command -v stdbuf >/dev/null 2>&1; then
  exec stdbuf -oL -eL bash "$PAYLOAD/bootstrap.sh"
fi
exec bash "$PAYLOAD/bootstrap.sh"
""".strip().replace("\r\n", "\n").replace("\r", "\n")

    dc = (volume_dc or VOLUME_DATACENTER).strip() or VOLUME_DATACENTER
    name = "photoreal-vol-check" if check_only else "photoreal-vol-sync"
    body: dict[str, Any] = {
        "name": name,
        "imageName": POD_IMAGE,
        "cloudType": "SECURE",
        "computeType": "CPU",
        "dataCenterIds": [dc],
        "vcpuCount": 4,
        # Scratch only — weights must land on the network volume (see bootstrap).
        # Keep modest headroom for pip / HF temp; do not rely on this for models.
        "containerDiskInGb": 40,
        "networkVolumeId": volume_id,
        "volumeMountPath": "/workspace",
        "ports": ["22/tcp"],
        "env": env,
        "dockerEntrypoint": ["/bin/bash", "-c"],
        "dockerStartCmd": [wrapper],
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
) -> tuple[bool, str]:
    """Return (ok, last_log_text) if PHOTOREAL_VOLUME_SYNC_OK seen in logs."""
    deadline = time.time() + timeout_s
    headers = {"Authorization": f"Bearer {api_key}"}
    saw_fail = False
    last_status = ""
    last_logs = ""
    while time.time() < deadline:
        try:
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
                if text != last_logs:
                    # Surface progress during multi-hour downloads (not only OK/FAIL).
                    progress = [
                        ln
                        for ln in text.splitlines()
                        if any(
                            k in ln
                            for k in (
                                "photoreal-vol-sync:",
                                "=== photoreal",
                                "Volume incomplete",
                                "Downloading",
                                "Fetching",
                                "download target",
                                "Cloning ComfyUI",
                                "PHOTOREAL_VOLUME",
                                "ERROR",
                                "Not enough free disk",
                                "pip ",
                            )
                        )
                    ]
                    if progress:
                        _emit(log, f"flash: pod… {progress[-1][-240:]}")
                last_logs = text
                if "PHOTOREAL_VOLUME_SYNC_OK" in text:
                    _emit(log, "flash: saw PHOTOREAL_VOLUME_SYNC_OK in pod logs")
                    return True, last_logs
                if "PHOTOREAL_VOLUME_SYNC_FAIL" in text:
                    saw_fail = True
                    _emit(log, "flash: saw PHOTOREAL_VOLUME_SYNC_FAIL in pod logs")
                    break
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ) as exc:
            # Local WiFi/DNS blips must not kill the remote download pod.
            _emit(log, f"flash: transient network error polling pod ({exc!s}); retrying…")
        time.sleep(15.0)

    # Final log scrape after exit
    text = _fetch_pod_logs_snapshot(http, api_key=api_key, pod_id=pod_id)
    if text:
        last_logs = text
        if "PHOTOREAL_VOLUME_SYNC_OK" in text:
            return True, last_logs
        if "PHOTOREAL_VOLUME_SYNC_FAIL" in text:
            saw_fail = True

    if saw_fail:
        return False, last_logs
    # Pod finished without log signal — caller may verify with check pod
    return False, last_logs


def _fetch_pod_logs_snapshot(
    http: httpx.Client, *, api_key: str, pod_id: str
) -> str:
    """
    Snapshot container/system logs via Runpod API v2 SSE.

    Docs: GET https://api.runpod.io/v2/pods/{id}/logs?tail=N
    Each event ``data:`` payload is ``{"source","line","ts"}``.
    ``rest.runpod.io/.../logs`` redirects to HTML docs — do not use it.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }
    url = f"https://api.runpod.io/v2/pods/{pod_id}/logs?tail=500"
    raw = ""
    try:
        with http.stream(
            "GET",
            url,
            headers=headers,
            timeout=httpx.Timeout(12.0, connect=10.0),
            follow_redirects=False,
        ) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                return (
                    "(pod logs redirected — expected api.runpod.io SSE; "
                    f"got HTTP {resp.status_code})"
                )
            if resp.status_code >= 400:
                return f"(pod logs HTTP {resp.status_code})"
            ctype = (resp.headers.get("content-type") or "").lower()
            parts: list[bytes] = []
            total = 0
            deadline = time.time() + 10.0
            try:
                for chunk in resp.iter_bytes():
                    if not chunk:
                        break
                    parts.append(chunk)
                    total += len(chunk)
                    if total >= 512_000 or time.time() >= deadline:
                        break
            except httpx.ReadTimeout:
                pass
            raw = b"".join(parts).decode("utf-8", errors="replace")
            if "text/html" in ctype or raw.lstrip().lower().startswith(
                ("<!doctype", "<html", "<a href=")
            ):
                return (
                    "(pod logs returned HTML/redirect — check RUNPOD_API_KEY "
                    "and use api.runpod.io, not rest.runpod.io)"
                )
    except Exception as exc:  # noqa: BLE001
        return f"(could not fetch pod logs: {exc})"

    lines_out: list[str] = []
    for block in raw.split("\n\n"):
        for line in block.split("\n"):
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                lines_out.append(payload)
                continue
            if isinstance(obj, dict):
                src = str(obj.get("source") or "").strip()
                ln = str(obj.get("line") or "").rstrip()
                if ln:
                    lines_out.append(f"[{src}] {ln}" if src else ln)
            elif payload:
                lines_out.append(payload)

    if lines_out:
        return "\n".join(lines_out)
    if raw.strip():
        return raw.strip()[-4000:]
    return ""


def _run_check_pod(
    http: httpx.Client,
    *,
    api_key: str,
    volume_id: str,
    volume_dc: str,
    timeout_s: float,
    log: LogFn | None,
) -> tuple[bool, str]:
    pod_id = _create_sync_pod(
        http,
        api_key=api_key,
        volume_id=volume_id,
        volume_dc=volume_dc,
        hf_token="",
        civitai="",
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
    "ensure_network_volume",
    "ensure_network_volume_id",
    "ensure_volume_models_ready",
    "sync_volume_models",
    "volume_missing_parts",
    "volume_models_complete",
    "volume_sync_flag_set",
    "volume_sync_needed",
]

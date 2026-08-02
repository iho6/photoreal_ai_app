"""Background character_inpaint jobs (scene + mask + character → lighting bake)."""

from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

INPAINT_DIR = REPO_ROOT / "data" / "outputs" / "character_inpaint"
OUTPUT_URL_PREFIX = "/inpaint-outputs"

_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def ensure_inpaint_dir() -> Path:
    INPAINT_DIR.mkdir(parents=True, exist_ok=True)
    return INPAINT_DIR


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "images": list(job.get("images") or []),
        "error": job.get("error"),
        "logs": list(job.get("logs") or []),
        "created": job.get("created"),
        "updated": job.get("updated"),
        "prompt": job.get("prompt") or "",
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return _job_public(job)


def _log(job_id: str, msg: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["logs"].append(msg)
        job["updated"] = time.time()


def _set(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated"] = time.time()


def start_inpaint(
    *,
    scene_path: Path,
    mask_path: Path,
    reference_path: Path,
    prompt: str = "",
    denoise: float = 0.95,
    comfy_url: str | None = None,
) -> dict[str, Any]:
    ensure_inpaint_dir()
    if not scene_path.is_file():
        raise ValueError("scene image is required")
    if not mask_path.is_file():
        raise ValueError("mask image is required")
    if not reference_path.is_file():
        raise ValueError("reference image is required")

    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    scene_s = INPAINT_DIR / f"_in_scene_{job_id}{scene_path.suffix or '.png'}"
    mask_s = INPAINT_DIR / f"_in_mask_{job_id}{mask_path.suffix or '.png'}"
    ref_s = INPAINT_DIR / f"_in_ref_{job_id}{reference_path.suffix or '.png'}"
    shutil.copy2(scene_path, scene_s)
    shutil.copy2(mask_path, mask_s)
    shutil.copy2(reference_path, ref_s)

    record: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "scene_path": str(scene_s),
        "mask_path": str(mask_s),
        "reference_path": str(ref_s),
        "prompt": (prompt or "").strip(),
        "denoise": float(denoise),
        "comfy_url": comfy_url,
        "images": [],
        "error": None,
        "logs": [],
        "created": now,
        "updated": now,
    }
    with _lock:
        _jobs[job_id] = record

    _log(job_id, f"job created id={job_id}")
    thread = threading.Thread(
        target=_run_job,
        args=(job_id,),
        name=f"char-inpaint-{job_id}",
        daemon=True,
    )
    thread.start()
    return _job_public(record)


def _run_job(job_id: str) -> None:
    with _lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        return
    try:
        _set(job_id, stage="inpaint")
        _log(job_id, "running CharacterInpaintPipeline…")
        from photoreal.pipelines.image.character_inpaint import (
            DEFAULT_PROMPT,
            CharacterInpaintPipeline,
        )

        prompt = job.get("prompt") or DEFAULT_PROMPT
        with _gpu_lock:
            paths = CharacterInpaintPipeline().run(
                scene_image=job["scene_path"],
                mask_image=job["mask_path"],
                reference_image=job["reference_path"],
                prompt=prompt,
                denoise=float(job.get("denoise") or 0.95),
                comfy_url=job.get("comfy_url"),
                output_dir=INPAINT_DIR,
            )
        urls = [f"{OUTPUT_URL_PREFIX}/{p.name}" for p in paths]
        _set(job_id, status="done", stage="complete", images=urls, error=None)
        _log(job_id, f"done images={urls}")
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="error", stage="failed", error=str(exc))
        _log(job_id, f"ERROR: {exc}")
        _log(job_id, traceback.format_exc())
    finally:
        for key in ("scene_path", "mask_path", "reference_path"):
            try:
                Path(job.get(key) or "").unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

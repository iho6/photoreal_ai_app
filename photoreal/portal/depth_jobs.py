"""Background depth convert jobs (DA3 + mask composite)."""

from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

DEPTH_DIR = REPO_ROOT / "data" / "outputs" / "depth_subject"
OUTPUT_URL_PREFIX = "/depth-outputs"

_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def ensure_depth_dir() -> Path:
    DEPTH_DIR.mkdir(parents=True, exist_ok=True)
    return DEPTH_DIR


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
        "feather_px": job.get("feather_px"),
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


def start_convert(
    *,
    image_path: Path,
    mask_path: Path,
    feather_px: int = 7,
    comfy_url: str | None = None,
) -> dict[str, Any]:
    ensure_depth_dir()
    if not image_path.is_file():
        raise ValueError("image file is required")
    if not mask_path.is_file():
        raise ValueError("mask file is required")

    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    img_staging = DEPTH_DIR / f"_in_img_{job_id}{image_path.suffix or '.png'}"
    mask_staging = DEPTH_DIR / f"_in_mask_{job_id}{mask_path.suffix or '.png'}"
    shutil.copy2(image_path, img_staging)
    shutil.copy2(mask_path, mask_staging)

    record: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "image_path": str(img_staging),
        "mask_path": str(mask_staging),
        "feather_px": int(feather_px),
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
        name=f"depth-convert-{job_id}",
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
        _set(job_id, stage="depth")
        _log(job_id, "running DepthSubjectPipeline…")
        from photoreal.pipelines.vision.depth_subject import DepthSubjectPipeline

        with _gpu_lock:
            paths = DepthSubjectPipeline().run(
                image=job["image_path"],
                mask=job["mask_path"],
                feather_px=int(job.get("feather_px") or 7),
                comfy_url=job.get("comfy_url"),
                output_dir=DEPTH_DIR,
            )
        urls = [f"{OUTPUT_URL_PREFIX}/{p.name}" for p in paths]
        _set(job_id, status="done", stage="complete", images=urls, error=None)
        _log(job_id, f"done images={urls}")
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="error", stage="failed", error=str(exc))
        _log(job_id, f"ERROR: {exc}")
        _log(job_id, traceback.format_exc())
    finally:
        for key in ("image_path", "mask_path"):
            try:
                Path(job.get(key) or "").unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

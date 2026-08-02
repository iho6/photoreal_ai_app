"""Background SAM3 segment jobs (local Comfy)."""

from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

SAM3_DIR = REPO_ROOT / "data" / "outputs" / "sam3_segment"
OUTPUT_URL_PREFIX = "/sam3-outputs"

_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def make_segment_cutout(
    frame_path: Path,
    mask_path: Path,
    out_path: Path,
) -> Path:
    """Person pixels from frame with alpha from mask (bg removed)."""
    from PIL import Image

    frame = Image.open(frame_path).convert("RGBA")
    mask = Image.open(mask_path).convert("L")
    if mask.size != frame.size:
        mask = mask.resize(frame.size, Image.Resampling.NEAREST)
    r, g, b, _a = frame.split()
    Image.merge("RGBA", (r, g, b, mask)).save(out_path)
    return out_path


def ensure_sam3_dir() -> Path:
    SAM3_DIR.mkdir(parents=True, exist_ok=True)
    return SAM3_DIR


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "job": job.get("job") or "image_mask",
        "text_prompt": job.get("text_prompt") or "",
        "images": list(job.get("images") or []),
        "frame_url": job.get("frame_url"),
        "cutout_url": job.get("cutout_url"),
        "error": job.get("error"),
        "logs": list(job.get("logs") or []),
        "created": job.get("created"),
        "updated": job.get("updated"),
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


def start_segment(
    *,
    image_path: Path,
    job: str = "image_mask",
    text_prompt: str = "",
    positive_coords: list[dict[str, Any]] | None = None,
    negative_coords: list[dict[str, Any]] | None = None,
    threshold: float = 0.5,
    refine_iterations: int = 2,
    comfy_url: str | None = None,
) -> dict[str, Any]:
    ensure_sam3_dir()
    if not image_path.is_file():
        raise ValueError("image file is required")

    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    # Persist a copy under job staging so the worker thread owns a stable path
    staging = SAM3_DIR / f"_inputs_{job_id}{image_path.suffix or '.png'}"
    shutil.copy2(image_path, staging)

    record: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "job": (job or "image_mask").strip().lower(),
        "text_prompt": (text_prompt or "").strip(),
        "positive_coords": list(positive_coords or []),
        "negative_coords": list(negative_coords or []),
        "threshold": float(threshold),
        "refine_iterations": int(refine_iterations),
        "comfy_url": comfy_url,
        "image_path": str(staging),
        "images": [],
        "frame_url": None,
        "cutout_url": None,
        "error": None,
        "logs": [],
        "created": now,
        "updated": now,
    }
    with _lock:
        _jobs[job_id] = record

    _log(job_id, f"job created id={job_id}")
    _log(job_id, f"queued job={record['job']!r} text={record['text_prompt']!r}")

    thread = threading.Thread(
        target=_run_job,
        args=(job_id,),
        name=f"sam3-seg-{job_id}",
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
        _set(job_id, stage="segment")
        _log(job_id, "running Sam3SegmentPipeline…")
        from photoreal.pipelines.vision.sam3_segment import Sam3SegmentPipeline

        # Keep a durable copy of the segmented frame for Convert Depth.
        frame_name = f"frame_{job_id}.png"
        frame_dest = SAM3_DIR / frame_name
        try:
            shutil.copy2(job["image_path"], frame_dest)
        except Exception as copy_exc:  # noqa: BLE001
            _log(job_id, f"WARN: could not persist frame copy: {copy_exc}")
            frame_dest = Path("")

        with _gpu_lock:
            paths = Sam3SegmentPipeline().run(
                image=job["image_path"],
                job=job.get("job") or "image_mask",
                positive_coords=job.get("positive_coords") or [],
                negative_coords=job.get("negative_coords") or [],
                text_prompt=job.get("text_prompt") or "",
                threshold=float(job.get("threshold") or 0.5),
                refine_iterations=int(job.get("refine_iterations") or 2),
                comfy_url=job.get("comfy_url"),
                output_dir=SAM3_DIR,
            )
        urls = [f"{OUTPUT_URL_PREFIX}/{p.name}" for p in paths]
        frame_url = (
            f"{OUTPUT_URL_PREFIX}/{frame_name}" if frame_dest.is_file() else None
        )
        cutout_url = None
        if frame_dest.is_file() and paths:
            cutout_name = f"cutout_{job_id}.png"
            cutout_dest = SAM3_DIR / cutout_name
            try:
                make_segment_cutout(frame_dest, paths[0], cutout_dest)
                cutout_url = f"{OUTPUT_URL_PREFIX}/{cutout_name}"
            except Exception as cut_exc:  # noqa: BLE001
                _log(job_id, f"WARN: could not build cutout: {cut_exc}")
        _set(
            job_id,
            status="done",
            stage="complete",
            images=urls,
            frame_url=frame_url,
            cutout_url=cutout_url,
            error=None,
        )
        _log(
            job_id,
            f"done images={urls} frame_url={frame_url} cutout_url={cutout_url}",
        )
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="error", stage="failed", error=str(exc))
        _log(job_id, f"ERROR: {exc}")
        _log(job_id, traceback.format_exc())
    finally:
        # Drop staging input (frame_{job_id}.png is kept when present)
        try:
            Path(job.get("image_path") or "").unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

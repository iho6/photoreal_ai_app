"""Background wan_animate jobs (Animation / Move + Extend chunks)."""

from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

WAN_ANIMATE_DIR = REPO_ROOT / "data" / "outputs" / "wan_animate"
OUTPUT_URL_PREFIX = "/wan-animate-outputs"

_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def ensure_wan_animate_dir() -> Path:
    WAN_ANIMATE_DIR.mkdir(parents=True, exist_ok=True)
    return WAN_ANIMATE_DIR


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "videos": list(job.get("videos") or []),
        "images": list(job.get("images") or []),
        "error": job.get("error"),
        "logs": list(job.get("logs") or []),
        "created": job.get("created"),
        "updated": job.get("updated"),
        "prompt": job.get("prompt") or "",
        "fps": job.get("fps"),
        "length": job.get("length"),
        "video_frame_offset": job.get("video_frame_offset"),
        "next_video_frame_offset": job.get("next_video_frame_offset"),
        "wanFps": job.get("fps"),
        "driving_frame_count": job.get("driving_frame_count"),
        "meta": job.get("meta") or {},
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


def start_wan_animate(
    *,
    character_path: Path,
    driving_path: Path,
    continue_motion_path: Path | None = None,
    prompt: str = "a person moving naturally, photorealistic",
    length: int = 77,
    offset: int = 0,
    fps: float | None = None,
    driving_frame_count: int | None = None,
    continue_motion_max_frames: int = 5,
    width: int = 832,
    height: int = 480,
    comfy_url: str | None = None,
) -> dict[str, Any]:
    ensure_wan_animate_dir()
    if not character_path.is_file():
        raise ValueError("character image is required")
    if not driving_path.is_file():
        raise ValueError("driving video is required")
    if continue_motion_path is not None and not continue_motion_path.is_file():
        raise ValueError("continue_motion video is invalid")

    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    char_s = (
        WAN_ANIMATE_DIR
        / f"_in_char_{job_id}{character_path.suffix or '.png'}"
    )
    drive_s = (
        WAN_ANIMATE_DIR
        / f"_in_drive_{job_id}{driving_path.suffix or '.mp4'}"
    )
    shutil.copy2(character_path, char_s)
    shutil.copy2(driving_path, drive_s)
    cont_s = None
    if continue_motion_path is not None:
        cont_s = (
            WAN_ANIMATE_DIR
            / f"_in_continue_{job_id}{continue_motion_path.suffix or '.mp4'}"
        )
        shutil.copy2(continue_motion_path, cont_s)

    record: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "character_path": str(char_s),
        "driving_path": str(drive_s),
        "continue_motion_path": str(cont_s) if cont_s else None,
        "prompt": (prompt or "").strip()
        or "a person moving naturally, photorealistic",
        "length": int(length),
        "offset": int(offset),
        "fps": float(fps) if fps is not None else None,
        "driving_frame_count": (
            int(driving_frame_count) if driving_frame_count is not None else None
        ),
        "continue_motion_max_frames": int(continue_motion_max_frames),
        "width": int(width),
        "height": int(height),
        "comfy_url": comfy_url,
        "videos": [],
        "images": [],
        "meta": {},
        "error": None,
        "logs": [],
        "created": now,
        "updated": now,
        "video_frame_offset": int(offset),
        "next_video_frame_offset": None,
    }
    with _lock:
        _jobs[job_id] = record

    _log(job_id, f"job created id={job_id}")
    thread = threading.Thread(
        target=_run_job,
        args=(job_id,),
        name=f"wan-animate-{job_id}",
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
        _set(job_id, stage="wan_animate")
        _log(job_id, "running WanAnimatePipeline…")
        from photoreal.pipelines.video.wan_animate import WanAnimatePipeline

        with _gpu_lock:
            paths = WanAnimatePipeline().run(
                character_image=job["character_path"],
                driving_video=job["driving_path"],
                continue_motion=job.get("continue_motion_path"),
                prompt=job.get("prompt") or "",
                length=int(job.get("length") or 77),
                video_frame_offset=int(job.get("offset") or 0),
                fps=job.get("fps"),
                driving_frame_count=job.get("driving_frame_count"),
                continue_motion_max_frames=int(
                    job.get("continue_motion_max_frames") or 5
                ),
                width=int(job.get("width") or 832),
                height=int(job.get("height") or 480),
                comfy_url=job.get("comfy_url"),
                output_dir=WAN_ANIMATE_DIR,
            )

        videos = [
            f"{OUTPUT_URL_PREFIX}/{p.name}"
            for p in paths
            if p.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}
        ]
        images = [
            f"{OUTPUT_URL_PREFIX}/{p.name}"
            for p in paths
            if p.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv", ".json"}
        ]
        meta: dict[str, Any] = {}
        if paths:
            meta_path = WAN_ANIMATE_DIR / f"{paths[0].stem}_meta.json"
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}

        _set(
            job_id,
            status="done",
            stage="complete",
            videos=videos,
            images=images,
            error=None,
            fps=meta.get("fps"),
            length=meta.get("length"),
            video_frame_offset=meta.get("video_frame_offset"),
            next_video_frame_offset=meta.get("next_video_frame_offset"),
            driving_frame_count=meta.get("driving_frame_count"),
            meta=meta,
        )
        _log(job_id, f"done videos={videos}")
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="error", stage="failed", error=str(exc))
        _log(job_id, f"ERROR: {exc}")
        _log(job_id, traceback.format_exc())
    finally:
        for key in ("character_path", "driving_path", "continue_motion_path"):
            try:
                p = job.get(key)
                if p:
                    Path(p).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

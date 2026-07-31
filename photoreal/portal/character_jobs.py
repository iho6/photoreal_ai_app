"""Background character generate jobs: reprompt → photoreal_gen."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from photoreal.portal.paths import REPO_ROOT

CHARACTERS_DIR = REPO_ROOT / "data" / "outputs" / "characters"
OUTPUT_URL_PREFIX = "/character-outputs"

_lock = threading.Lock()
_gpu_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def ensure_characters_dir() -> Path:
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    return CHARACTERS_DIR


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "prompt": job.get("prompt") or "",
        "rewritten": job.get("rewritten"),
        "images": list(job.get("images") or []),
        "error": job.get("error"),
        "logs": list(job.get("logs") or []),
        "created": job.get("created"),
        "updated": job.get("updated"),
        "backend": job.get("backend"),
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return _job_public(job)


def list_gallery() -> list[dict[str, Any]]:
    ensure_characters_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(CHARACTERS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.endswith("_meta.png"):
            continue
        st = path.stat()
        items.append(
            {
                "id": path.stem,
                "url": f"{OUTPUT_URL_PREFIX}/{path.name}",
                "name": path.name,
                "created": st.st_mtime,
            }
        )
    return items


def start_generate(prompt: str) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt is required")

    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    job: dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "prompt": text,
        "rewritten": None,
        "images": [],
        "error": None,
        "logs": [],
        "created": now,
        "updated": now,
        "backend": None,
    }
    with _lock:
        _jobs[job_id] = job

    _log(job_id, f"job created id={job_id}")
    _log(job_id, f"queued prompt={text!r}")

    thread = threading.Thread(
        target=_run_job,
        args=(job_id,),
        name=f"character-gen-{job_id}",
        daemon=True,
    )
    thread.start()
    return _job_public(job)


def _update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated"] = time.time()


def _log(job_id: str, line: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    text = f"[{ts}] {line}"
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append(text)
        job["updated"] = time.time()


def _truncate(s: str, limit: int = 4000) -> str:
    s = s or ""
    if len(s) <= limit:
        return s
    return s[:limit] + f"… (+{len(s) - limit} chars)"


def _images_from_paths(paths: list[Path]) -> list[dict[str, str]]:
    images = []
    for p in paths:
        path = Path(p)
        images.append(
            {
                "id": path.stem,
                "url": f"{OUTPUT_URL_PREFIX}/{path.name}",
                "name": path.name,
            }
        )
    return images


def _run_job(job_id: str) -> None:
    with _lock:
        prompt = str(_jobs[job_id]["prompt"])

    acquired = False
    try:
        from photoreal.portal.env_check import assert_generate_env

        try:
            env_info = assert_generate_env(log=lambda msg: _log(job_id, msg))
        except RuntimeError as exc:
            _log(job_id, f"ERROR: {exc}")
            _update(job_id, status="error", stage="error", error=str(exc))
            return

        backend = env_info.get("backend") or "local"
        # Belt-and-suspenders: never run local VLM/Comfy without CUDA.
        from photoreal.portal.env_check import torch_cuda_available

        if backend == "local" and not torch_cuda_available():
            backend = "runpod"
            _log(job_id, "backend overridden to runpod (no local CUDA)")
        _update(job_id, backend=backend)
        _log(job_id, f"backend={backend}")

        if backend == "runpod":
            _run_via_flash(job_id, prompt)
            return

        _log(job_id, "waiting for GPU lock…")
        acquired = _gpu_lock.acquire(blocking=True)
        _log(job_id, "GPU lock acquired")
        _update(job_id, stage="reprompt", status="running", error=None)
        _log(job_id, "reprompt: start")
        _log(job_id, f"reprompt: user prompt = {prompt!r}")

        from photoreal.pipelines.vision.reprompt import RepromptPipeline

        rewritten = RepromptPipeline().run(
            prompt=prompt,
            unload=True,
            log=lambda msg: _log(job_id, msg),
        )
        _update(job_id, rewritten=rewritten, stage="gen")
        _log(job_id, f"reprompt: rewritten = {_truncate(rewritten, 2000)!r}")
        _log(job_id, "gen: start (photoreal_gen → ComfyUI)")

        try:
            from photoreal.config import get_settings

            settings = get_settings()
            comfy = getattr(settings, "comfy_url", "http://127.0.0.1:8188")
            _log(job_id, f"gen: comfy_url = {comfy}")
        except Exception as exc:  # noqa: BLE001
            _log(job_id, f"gen: could not read settings ({exc})")

        ensure_characters_dir()
        _log(job_id, f"gen: output_dir = {CHARACTERS_DIR}")
        from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline

        paths = PhotorealGenPipeline().run(
            prompt=rewritten,
            output_dir=CHARACTERS_DIR,
        )
        images = _images_from_paths([Path(p) for p in paths])
        for img in images:
            _log(job_id, f"gen: saved {img['name']} → {img['url']}")

        _update(job_id, images=images, stage="done", status="done")
        _log(job_id, f"done ({len(images)} image(s))")
    except Exception as exc:  # noqa: BLE001 — surface to client
        _log(job_id, f"ERROR: {exc}")
        for line in traceback.format_exc().splitlines():
            _log(job_id, line)
        _update(job_id, status="error", stage="error", error=str(exc))
    finally:
        if acquired:
            _gpu_lock.release()
            _log(job_id, "GPU lock released")


def _run_via_flash(job_id: str, prompt: str) -> None:
    _update(job_id, stage="runpod", status="running", error=None)
    ensure_characters_dir()
    from photoreal.flash.client import run_character_via_runpod

    result = run_character_via_runpod(
        prompt,
        output_dir=CHARACTERS_DIR,
        log=lambda msg: _log(job_id, msg),
    )
    rewritten = result.get("rewritten")
    if rewritten:
        _update(job_id, rewritten=rewritten)

    paths = [Path(x["path"]) for x in result.get("images") or []]
    images = _images_from_paths(paths)
    for img in images:
        _log(job_id, f"gen: saved {img['name']} → {img['url']}")

    _update(job_id, images=images, stage="done", status="done")
    _log(job_id, f"done ({len(images)} image(s)) backend=runpod")

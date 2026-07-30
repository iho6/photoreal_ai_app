"""Stage-2 bootstrap: install extras, download weights, start services."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from photoreal.portal.credentials import apply_env_to_process
from photoreal.portal.install_probe import (
    comfy_install_satisfied,
    extras_deps_satisfied,
    write_comfy_stamp,
)
from photoreal.portal.logstream import (
    feed_cr_lf,
    flush_cr_lf,
    format_progress_bar,
    parse_percent,
    parse_progress_mark,
)
from photoreal.portal.paths import (
    COMFY_REQUIREMENTS,
    DOWNLOAD_SCRIPT,
    REPO_ROOT,
    venv_python,
)
from photoreal.portal.supervisor import start_all


LogFn = Callable[..., None]  # emit(line, mode="append")


class LaunchCancelled(Exception):
    """Stage-2 aborted because a newer Launch started or cancel was requested."""


@dataclass
class LaunchState:
    running: bool = False
    finished: bool = False
    ok: bool = False
    error: str | None = None
    generation: int = 0
    log_epoch: int = 0
    lines: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=2000))
    progress_pct: float | None = None
    progress_label: str = ""
    progress_seq: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _proc: subprocess.Popen[bytes] | None = None
    _worker: threading.Thread | None = None

    def emit(self, line: str, mode: str = "append") -> None:
        """Append a status line, or update live download progress."""
        with self._cond:
            if mode == "progress":
                self._set_progress_unlocked(line)
                return
            self.lines.append({"line": line, "mode": "append"})
            self._cond.notify_all()

    def _set_progress_unlocked(self, line: str) -> None:
        marked = parse_progress_mark(line)
        if marked is not None:
            pct, label = marked
        else:
            pct = parse_percent(line)
            label = line.strip()
        if pct is None:
            # Keep prior percent if this is a label-only tick.
            pct = self.progress_pct
        else:
            pct = max(0.0, min(100.0, float(pct)))
        if not label:
            label = self.progress_label or "download"
        if len(label) > 80:
            label = label[:77] + "…"
        bar = format_progress_bar(pct if pct is not None else 0.0, label)
        self.progress_pct = pct if pct is not None else 0.0
        self.progress_label = bar
        self.progress_seq += 1
        self._cond.notify_all()

    def set_progress(self, line: str) -> None:
        with self._cond:
            self._set_progress_unlocked(line)

    def clear_progress(self) -> None:
        with self._cond:
            self.progress_pct = None
            self.progress_label = ""
            self.progress_seq += 1
            self._cond.notify_all()


STATE = LaunchState()


def _check_cancel(cancel: threading.Event, generation: int) -> None:
    if cancel.is_set() or generation != STATE.generation:
        raise LaunchCancelled("Launch cancelled — a new run replaced this one")


def _gated_emit(generation: int) -> LogFn:
    def emit(line: str, mode: str = "append") -> None:
        if generation != STATE.generation:
            return
        if mode == "progress":
            STATE.set_progress(line)
            return
        STATE.emit(line, "append")

    return emit


def _run_logged(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    emit: LogFn,
    cancel: threading.Event,
    generation: int,
) -> int:
    _check_cancel(cancel, generation)
    emit(f"$ {' '.join(cmd)}", "append")
    child_env = dict(env)
    child_env["PYTHONUNBUFFERED"] = "1"
    # Allow HF/Civitai \\r percent lines — portal maps them to the UI bar.
    child_env.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)
    child_env.pop("TQDM_DISABLE", None)
    child_env["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    STATE._proc = proc
    assert proc.stdout is not None
    buf = ""
    try:
        while True:
            if cancel.is_set() or generation != STATE.generation:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                raise LaunchCancelled("Launch cancelled during subprocess")
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            buf, events = feed_cr_lf(buf, text)
            for line, mode in events:
                emit(line, mode)
        for line, mode in flush_cr_lf(buf):
            emit(line, mode)
        STATE.clear_progress()
        return proc.wait()
    finally:
        if STATE._proc is proc:
            STATE._proc = None


def cancel_launch(*, timeout: float = 8.0) -> None:
    """Stop the in-flight Stage-2 worker and its child process."""
    STATE.cancel.set()
    STATE.generation += 1  # invalidate in-flight worker checks immediately
    proc = STATE._proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except OSError:
                pass

    worker = STATE._worker
    if worker is not None and worker.is_alive():
        worker.join(timeout=timeout)

    with STATE._cond:
        STATE.running = False
        STATE.finished = True
        STATE._proc = None
        STATE._worker = None
        STATE._cond.notify_all()


def run_stage2(
    *,
    emit: LogFn | None = None,
    cancel: threading.Event | None = None,
    generation: int | None = None,
) -> None:
    """Blocking Stage-2. Safe to call from a worker thread."""
    generation = STATE.generation if generation is None else generation
    log = emit or _gated_emit(generation)
    cancel = cancel or STATE.cancel
    tokens = apply_env_to_process()
    if not tokens.get("HF_TOKEN"):
        raise ValueError("HF_TOKEN missing — Save credentials before Launch")

    py = str(venv_python())
    env = os.environ.copy()

    def step(title: str, fn: Callable[[], None]) -> None:
        _check_cancel(cancel, generation)
        log(f"=== {title} ===", "append")
        fn()

    def install_extras() -> None:
        if extras_deps_satisfied():
            log("skip (already installed): photoreal-gen+vlm", "append")
            return
        code = _run_logged(
            [py, "-m", "pip", "install", "-e", ".[photoreal-gen,vlm]"],
            cwd=REPO_ROOT,
            env=env,
            emit=log,
            cancel=cancel,
            generation=generation,
        )
        if code != 0:
            raise RuntimeError(f"step failed ({code}): Install photoreal-gen + vlm extras")

    def install_comfy() -> None:
        if not COMFY_REQUIREMENTS.is_file():
            log(f"WARNING: {COMFY_REQUIREMENTS} missing — skip", "append")
            return
        if comfy_install_satisfied():
            log("skip (already installed): curated Comfy requirements", "append")
            return
        code = _run_logged(
            [py, "-m", "pip", "install", "-r", str(COMFY_REQUIREMENTS)],
            cwd=REPO_ROOT,
            env=env,
            emit=log,
            cancel=cancel,
            generation=generation,
        )
        if code != 0:
            raise RuntimeError(
                f"step failed ({code}): Install ComfyUI requirements (curated)"
            )
        write_comfy_stamp()
        log("wrote comfy requirements stamp", "append")

    def download_models() -> None:
        code = _run_logged(
            [py, str(DOWNLOAD_SCRIPT), "--all"],
            cwd=REPO_ROOT,
            env=env,
            emit=log,
            cancel=cancel,
            generation=generation,
        )
        if code != 0:
            raise RuntimeError(f"step failed ({code}): Download models (--all)")

    step("Install photoreal-gen + vlm extras", install_extras)
    step("Install ComfyUI requirements (curated)", install_comfy)
    step("Download models (--all)", download_models)

    _check_cancel(cancel, generation)
    log("=== Starting services (API + Comfy) ===", "append")
    result = start_all(ensure_comfy=True)
    for n in result.get("notes") or []:
        log(str(n), "append")
    if result.get("attach"):
        log(f"Attach: {result['attach']}", "append")
    if result.get("logs"):
        log(f"Logs: {result['logs']}", "append")
    health = result.get("health") or {}
    log(f"Health: {health}", "append")
    log("=== Launch complete ===", "append")


def start_launch_async(*, force: bool = True) -> dict[str, Any]:
    """
    Start Stage-2 in a background thread.

    Always cancels any in-flight Launch and starts over (force is accepted for
    API compat but ignored — relaunch must never 409).
    """
    _ = force
    replaced = False
    if STATE.running or (STATE._worker is not None and STATE._worker.is_alive()):
        cancel_launch(timeout=8.0)
        replaced = True
        time.sleep(0.2)

    # Orphan guard: flag stuck true with dead worker
    with STATE._cond:
        if STATE.running and (STATE._worker is None or not STATE._worker.is_alive()):
            STATE.running = False
            STATE.finished = True

    with STATE._cond:
        STATE.running = True
        STATE.finished = False
        STATE.ok = False
        STATE.error = None
        STATE.lines.clear()
        STATE.log_epoch += 1
        STATE.progress_pct = None
        STATE.progress_label = ""
        STATE.progress_seq += 1
        STATE.cancel.clear()
        STATE.generation += 1
        generation = STATE.generation
        log_epoch = STATE.log_epoch

    emit = _gated_emit(generation)

    def _worker() -> None:
        try:
            run_stage2(
                emit=emit,
                cancel=STATE.cancel,
                generation=generation,
            )
            with STATE._cond:
                if generation == STATE.generation:
                    STATE.ok = True
        except LaunchCancelled as e:
            with STATE._cond:
                if generation == STATE.generation:
                    STATE.ok = False
                    STATE.error = str(e)
                    emit(f"cancelled: {e}", "append")
        except Exception as e:  # noqa: BLE001
            with STATE._cond:
                if generation == STATE.generation:
                    STATE.ok = False
                    # Keep errors short in the log
                    msg = str(e).strip().splitlines()[0][:240]
                    STATE.error = msg
                    emit(f"ERROR: {msg}", "append")
        finally:
            STATE.clear_progress()
            with STATE._cond:
                if generation == STATE.generation:
                    STATE.running = False
                    STATE.finished = True
                    STATE._worker = None
                    STATE._cond.notify_all()

    worker = threading.Thread(target=_worker, name="photoreal-launch", daemon=True)
    STATE._worker = worker
    worker.start()
    return {"started": True, "replaced": replaced, "epoch": log_epoch}

"""FastAPI app: portal static UI + credentials / launch API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from photoreal.config import get_settings
from photoreal.portal import bootstrap
from photoreal.portal import character_jobs
from photoreal.portal.credentials import load_credentials, save_credentials
from photoreal.portal.paths import WEB_ROOT
from photoreal.portal.supervisor import dry_run_commands, health_snapshot


class CredentialsIn(BaseModel):
    hf_token: str | None = None
    civitai_api_token: str | None = None
    github_token: str | None = None
    runpod_api_key: str | None = None
    flash_character_endpoint: str | None = None
    generate_backend: str | None = None
    git_user_name: str | None = None
    git_user_email: str | None = None


class LaunchIn(BaseModel):
    # Optional re-save before launch
    credentials: CredentialsIn | None = None
    force: bool = Field(
        default=True,
        description="Cancel in-flight Launch and restart (default true)",
    )


class CharacterGenerateIn(BaseModel):
    prompt: str = Field(..., min_length=1)


def create_app() -> FastAPI:
    app = FastAPI(title="Photoreal Portal", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        settings = get_settings()
        creds = load_credentials()
        return {
            "health": health_snapshot(),
            "credentials": creds,
            "launch": {
                "running": bootstrap.STATE.running,
                "finished": bootstrap.STATE.finished,
                "ok": bootstrap.STATE.ok,
                "error": bootstrap.STATE.error,
            },
            "api": {
                "host": settings.api_host,
                "port": settings.api_port,
            },
            "commands_dry_run": dry_run_commands(),
        }

    @app.get("/api/credentials")
    def get_credentials() -> dict[str, Any]:
        return load_credentials()

    @app.post("/api/credentials")
    def post_credentials(body: CredentialsIn) -> dict[str, Any]:
        try:
            out = save_credentials(
                hf_token=body.hf_token,
                civitai_api_token=body.civitai_api_token,
                github_token=body.github_token,
                runpod_api_key=body.runpod_api_key,
                flash_character_endpoint=body.flash_character_endpoint,
                generate_backend=body.generate_backend,
                git_user_name=body.git_user_name,
                git_user_email=body.git_user_email,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        from photoreal.flash.gha_secrets import try_sync_actions_secrets_from_portal

        warn = try_sync_actions_secrets_from_portal()
        if warn:
            out = {**out, "actions_secrets_warning": warn}
        return out

    @app.post("/api/launch")
    def post_launch(body: LaunchIn | None = None) -> dict[str, Any]:
        body = body or LaunchIn()
        if body.credentials is not None:
            try:
                save_credentials(
                    hf_token=body.credentials.hf_token,
                    civitai_api_token=body.credentials.civitai_api_token,
                    github_token=body.credentials.github_token,
                    runpod_api_key=body.credentials.runpod_api_key,
                    flash_character_endpoint=body.credentials.flash_character_endpoint,
                    generate_backend=body.credentials.generate_backend,
                    git_user_name=body.credentials.git_user_name,
                    git_user_email=body.credentials.git_user_email,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            from photoreal.flash.gha_secrets import try_sync_actions_secrets_from_portal

            try_sync_actions_secrets_from_portal()
        # Always restart — never 409 on relaunch
        result = bootstrap.start_launch_async(force=True)
        return result

    @app.get("/api/launch/logs")
    async def launch_logs(after: int = 0) -> StreamingResponse:
        async def event_gen():
            idx = max(0, int(after))
            last_prog_seq = -1
            # None = not yet synced; avoids treating the first tick as a Launch reset
            # (which was clearing the UI / restarting the spinner on SSE reconnect).
            last_epoch: int | None = None
            while True:
                reset = False
                batch: list[Any] = []
                prog_payload: dict[str, Any] | None = None
                done = False
                ok = False
                err: str | None = None
                epoch = 0

                with bootstrap.STATE._cond:
                    epoch = bootstrap.STATE.log_epoch
                    if last_epoch is None:
                        last_epoch = epoch
                    elif epoch != last_epoch:
                        idx = 0
                        last_epoch = epoch
                        last_prog_seq = -1
                        reset = True

                    waiting = (
                        idx >= len(bootstrap.STATE.lines)
                        and bootstrap.STATE.progress_seq == last_prog_seq
                        and bootstrap.STATE.running
                    )
                    if not waiting:
                        batch = list(bootstrap.STATE.lines)[idx:]
                        if bootstrap.STATE.progress_seq != last_prog_seq:
                            last_prog_seq = bootstrap.STATE.progress_seq
                            prog_payload = {
                                "epoch": epoch,
                                "progress": bootstrap.STATE.progress_pct,
                                "label": bootstrap.STATE.progress_label,
                            }
                        done = (
                            bootstrap.STATE.finished
                            and idx + len(batch) >= len(bootstrap.STATE.lines)
                            and bootstrap.STATE.progress_seq == last_prog_seq
                        )
                        ok = bootstrap.STATE.ok
                        err = bootstrap.STATE.error

                if waiting:
                    await asyncio.sleep(0.2)
                    continue

                if reset:
                    yield f"data: {json.dumps({'epoch': epoch, 'reset': True})}\n\n"

                if prog_payload is not None:
                    yield f"data: {json.dumps(prog_payload)}\n\n"

                for ev in batch:
                    idx += 1
                    if isinstance(ev, dict):
                        line = ev.get("line", "")
                    else:
                        line = str(ev)
                    yield f"data: {json.dumps({'epoch': epoch, 'i': idx, 'line': line, 'mode': 'append'})}\n\n"

                if done:
                    # Always clear progress on completion (success or failure).
                    yield f"data: {json.dumps({'epoch': epoch, 'progress': None, 'label': ''})}\n\n"
                    yield f"data: {json.dumps({'done': True, 'ok': ok, 'error': err, 'epoch': epoch})}\n\n"
                    break

                await asyncio.sleep(0.05)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/character/generate")
    def character_generate(body: CharacterGenerateIn) -> dict[str, Any]:
        try:
            return character_jobs.start_generate(body.prompt)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/character/jobs/{job_id}")
    def character_job(job_id: str) -> dict[str, Any]:
        job = character_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/character/gallery")
    def character_gallery() -> dict[str, Any]:
        return {"items": character_jobs.list_gallery()}

    portal_dir = WEB_ROOT / "portal"
    timeline_dir = WEB_ROOT / "timeline"
    character_dir = WEB_ROOT / "character"
    ui_dir = WEB_ROOT / "ui"

    @app.get("/")
    def index() -> FileResponse:
        index_path = portal_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=500, detail="portal UI missing")
        return FileResponse(index_path)

    @app.get("/timeline")
    @app.get("/timeline/")
    def timeline() -> FileResponse:
        index_path = timeline_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=500, detail="timeline UI missing")
        return FileResponse(index_path)

    @app.get("/character")
    @app.get("/character/")
    def character_page() -> FileResponse:
        index_path = character_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=500, detail="character UI missing")
        return FileResponse(index_path)

    character_jobs.ensure_characters_dir()

    if ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dir)), name="ui")
    if portal_dir.is_dir():
        app.mount("/portal", StaticFiles(directory=str(portal_dir)), name="portal")
    if timeline_dir.is_dir():
        app.mount(
            "/timeline-assets",
            StaticFiles(directory=str(timeline_dir)),
            name="timeline",
        )
    if character_dir.is_dir():
        app.mount(
            "/character-assets",
            StaticFiles(directory=str(character_dir)),
            name="character",
        )
    app.mount(
        "/character-outputs",
        StaticFiles(directory=str(character_jobs.CHARACTERS_DIR)),
        name="character_outputs",
    )

    return app

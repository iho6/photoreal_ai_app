"""FastAPI app: portal static UI + credentials / launch API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from photoreal.config import get_settings
from photoreal.portal import bootstrap
from photoreal.portal import character_jobs
from photoreal.portal import character_inpaint_jobs
from photoreal.portal import character_pose_lock_jobs
from photoreal.portal import depth_jobs
from photoreal.portal import sam3_jobs
from photoreal.portal import voice_vosk
from photoreal.portal import wan_animate_jobs
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

    @app.post("/api/sam3/segment")
    async def sam3_segment(
        image: UploadFile = File(...),
        job: str = Form("image_mask"),
        text_prompt: str = Form(""),
        positive_coords: str = Form("[]"),
        negative_coords: str = Form("[]"),
        threshold: float = Form(0.5),
        refine_iterations: int = Form(2),
        comfy_url: str | None = Form(None),
    ) -> dict[str, Any]:
        """Enqueue SAM3 segmentation (multipart: image + optional text/points)."""
        import json as _json
        import tempfile

        try:
            pos = _json.loads(positive_coords or "[]")
            neg = _json.loads(negative_coords or "[]")
        except _json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"invalid coords JSON: {e}") from e
        if not isinstance(pos, list) or not isinstance(neg, list):
            raise HTTPException(status_code=400, detail="coords must be JSON lists")

        suffix = Path(image.filename or "input.png").suffix or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            data = await image.read()
            if not data:
                raise HTTPException(status_code=400, detail="empty image upload")
            tmp.write(data)
            tmp.close()
            return sam3_jobs.start_segment(
                image_path=Path(tmp.name),
                job=job,
                text_prompt=text_prompt,
                positive_coords=pos,
                negative_coords=neg,
                threshold=threshold,
                refine_iterations=refine_iterations,
                comfy_url=comfy_url or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    @app.get("/api/sam3/jobs/{job_id}")
    def sam3_job(job_id: str) -> dict[str, Any]:
        job = sam3_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/depth/convert")
    async def depth_convert(
        image: UploadFile = File(...),
        mask: UploadFile = File(...),
        feather_px: int = Form(7),
        comfy_url: str | None = Form(None),
    ) -> dict[str, Any]:
        """Enqueue person-only depth convert (multipart: image + SAM mask)."""
        import tempfile

        img_suffix = Path(image.filename or "frame.png").suffix or ".png"
        mask_suffix = Path(mask.filename or "mask.png").suffix or ".png"
        img_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=img_suffix)
        mask_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=mask_suffix)
        try:
            img_data = await image.read()
            mask_data = await mask.read()
            if not img_data:
                raise HTTPException(status_code=400, detail="empty image upload")
            if not mask_data:
                raise HTTPException(status_code=400, detail="empty mask upload")
            img_tmp.write(img_data)
            img_tmp.close()
            mask_tmp.write(mask_data)
            mask_tmp.close()
            return depth_jobs.start_convert(
                image_path=Path(img_tmp.name),
                mask_path=Path(mask_tmp.name),
                feather_px=feather_px,
                comfy_url=comfy_url or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            for tmp in (img_tmp, mask_tmp):
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass

    @app.get("/api/depth/jobs/{job_id}")
    def depth_job(job_id: str) -> dict[str, Any]:
        job = depth_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/character/inpaint")
    async def character_inpaint(
        scene: UploadFile = File(...),
        mask: UploadFile = File(...),
        reference: UploadFile = File(...),
        prompt: str = Form(""),
        denoise: float = Form(0.95),
        comfy_url: str | None = Form(None),
    ) -> dict[str, Any]:
        """Enqueue character-into-scene inpaint (multipart: scene + mask + reference)."""
        import tempfile

        scene_suf = Path(scene.filename or "scene.png").suffix or ".png"
        mask_suf = Path(mask.filename or "mask.png").suffix or ".png"
        ref_suf = Path(reference.filename or "reference.png").suffix or ".png"
        scene_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=scene_suf)
        mask_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=mask_suf)
        ref_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ref_suf)
        try:
            scene_data = await scene.read()
            mask_data = await mask.read()
            ref_data = await reference.read()
            if not scene_data:
                raise HTTPException(status_code=400, detail="empty scene upload")
            if not mask_data:
                raise HTTPException(status_code=400, detail="empty mask upload")
            if not ref_data:
                raise HTTPException(status_code=400, detail="empty reference upload")
            scene_tmp.write(scene_data)
            scene_tmp.close()
            mask_tmp.write(mask_data)
            mask_tmp.close()
            ref_tmp.write(ref_data)
            ref_tmp.close()
            return character_inpaint_jobs.start_inpaint(
                scene_path=Path(scene_tmp.name),
                mask_path=Path(mask_tmp.name),
                reference_path=Path(ref_tmp.name),
                prompt=prompt,
                denoise=denoise,
                comfy_url=comfy_url or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            for tmp in (scene_tmp, mask_tmp, ref_tmp):
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass

    @app.get("/api/character/inpaint/jobs/{job_id}")
    def character_inpaint_job(job_id: str) -> dict[str, Any]:
        job = character_inpaint_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/character/pose-lock")
    async def character_pose_lock(
        depth: UploadFile = File(...),
        reference: UploadFile = File(...),
        prompt: str = Form("refcontrol"),
        comfy_url: str | None = Form(None),
    ) -> dict[str, Any]:
        """Enqueue pose lock via RefControl depth (multipart: depth + lighting bake)."""
        import tempfile

        depth_suf = Path(depth.filename or "depth.png").suffix or ".png"
        ref_suf = Path(reference.filename or "bake.png").suffix or ".png"
        depth_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=depth_suf)
        ref_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ref_suf)
        try:
            depth_data = await depth.read()
            ref_data = await reference.read()
            if not depth_data:
                raise HTTPException(status_code=400, detail="empty depth upload")
            if not ref_data:
                raise HTTPException(status_code=400, detail="empty reference upload")
            depth_tmp.write(depth_data)
            depth_tmp.close()
            ref_tmp.write(ref_data)
            ref_tmp.close()
            return character_pose_lock_jobs.start_pose_lock(
                depth_path=Path(depth_tmp.name),
                reference_path=Path(ref_tmp.name),
                prompt=prompt,
                comfy_url=comfy_url or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            for tmp in (depth_tmp, ref_tmp):
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass

    @app.get("/api/character/pose-lock/jobs/{job_id}")
    def character_pose_lock_job(job_id: str) -> dict[str, Any]:
        job = character_pose_lock_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/wan-animate")
    async def wan_animate(
        character: UploadFile = File(...),
        video: UploadFile = File(...),
        continue_motion: UploadFile | None = File(None),
        prompt: str = Form("a person moving naturally, photorealistic"),
        length: int = Form(77),
        offset: int = Form(0),
        fps: float | None = Form(None),
        driving_frame_count: int | None = Form(None),
        continue_motion_max_frames: int = Form(5),
        width: int = Form(832),
        height: int = Form(480),
        comfy_url: str | None = Form(None),
    ) -> dict[str, Any]:
        """Enqueue Wan Animate chunk (multipart: character still + driving video)."""
        import tempfile

        char_suf = Path(character.filename or "character.png").suffix or ".png"
        vid_suf = Path(video.filename or "driving.mp4").suffix or ".mp4"
        char_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=char_suf)
        vid_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=vid_suf)
        cont_tmp = None
        try:
            char_data = await character.read()
            vid_data = await video.read()
            if not char_data:
                raise HTTPException(status_code=400, detail="empty character upload")
            if not vid_data:
                raise HTTPException(status_code=400, detail="empty video upload")
            char_tmp.write(char_data)
            char_tmp.close()
            vid_tmp.write(vid_data)
            vid_tmp.close()
            cont_path = None
            if continue_motion is not None and continue_motion.filename:
                cont_data = await continue_motion.read()
                if cont_data:
                    cont_suf = (
                        Path(continue_motion.filename or "continue.mp4").suffix
                        or ".mp4"
                    )
                    cont_tmp = tempfile.NamedTemporaryFile(
                        delete=False, suffix=cont_suf
                    )
                    cont_tmp.write(cont_data)
                    cont_tmp.close()
                    cont_path = Path(cont_tmp.name)
            return wan_animate_jobs.start_wan_animate(
                character_path=Path(char_tmp.name),
                driving_path=Path(vid_tmp.name),
                continue_motion_path=cont_path,
                prompt=prompt,
                length=length,
                offset=offset,
                fps=fps,
                driving_frame_count=driving_frame_count,
                continue_motion_max_frames=continue_motion_max_frames,
                width=width,
                height=height,
                comfy_url=comfy_url or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            for tmp in (char_tmp, vid_tmp, cont_tmp):
                if tmp is None:
                    continue
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass

    @app.get("/api/wan-animate/jobs/{job_id}")
    def wan_animate_job(job_id: str) -> dict[str, Any]:
        job = wan_animate_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/voice/status")
    def voice_status() -> dict[str, Any]:
        return voice_vosk.status()

    @app.post("/api/voice/command")
    async def voice_command(
        request: Request,
        sample_rate: int = 16000,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Accept raw s16le mono PCM; return start|stop|none (local Vosk)."""
        if reset:
            voice_vosk.reset_recognizer()
        body = await request.body()
        try:
            return voice_vosk.process_pcm(body, sample_rate=sample_rate)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    portal_dir = WEB_ROOT / "portal"
    timeline_dir = WEB_ROOT / "timeline"
    character_dir = WEB_ROOT / "character"
    reference_dir = WEB_ROOT / "reference"
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
    sam3_jobs.ensure_sam3_dir()
    depth_jobs.ensure_depth_dir()

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
    if reference_dir.is_dir():
        app.mount(
            "/reference-assets",
            StaticFiles(directory=str(reference_dir)),
            name="reference",
        )
    app.mount(
        "/character-outputs",
        StaticFiles(directory=str(character_jobs.CHARACTERS_DIR)),
        name="character_outputs",
    )
    app.mount(
        "/sam3-outputs",
        StaticFiles(directory=str(sam3_jobs.SAM3_DIR)),
        name="sam3_outputs",
    )
    app.mount(
        "/depth-outputs",
        StaticFiles(directory=str(depth_jobs.DEPTH_DIR)),
        name="depth_outputs",
    )
    character_inpaint_jobs.ensure_inpaint_dir()
    character_pose_lock_jobs.ensure_pose_lock_dir()
    wan_animate_jobs.ensure_wan_animate_dir()
    app.mount(
        "/inpaint-outputs",
        StaticFiles(directory=str(character_inpaint_jobs.INPAINT_DIR)),
        name="inpaint_outputs",
    )
    app.mount(
        "/pose-lock-outputs",
        StaticFiles(directory=str(character_pose_lock_jobs.POSE_LOCK_DIR)),
        name="pose_lock_outputs",
    )
    app.mount(
        "/wan-animate-outputs",
        StaticFiles(directory=str(wan_animate_jobs.WAN_ANIMATE_DIR)),
        name="wan_animate_outputs",
    )

    return app

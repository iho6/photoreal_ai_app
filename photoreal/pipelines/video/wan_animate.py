"""wan_animate — Wan2.2 Animate Animation (Move) mode via ComfyUI."""

from __future__ import annotations

import copy
import json
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "wan_animate_api.json"

DIFFUSION_NAME = "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors"
LORA_NAME = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
VITPOSE_NAME = "vitpose-l-wholebody.onnx"
YOLO_NAME = "yolov10m.onnx"

DEFAULT_PROMPT = "a person moving naturally, photorealistic"
DEFAULT_NEGATIVE = "blurry, low quality, distorted face, deformed hands"
MAX_CHUNK_LENGTH = 77
DEFAULT_CONTINUE_MOTION_MAX_FRAMES = 5


def align_dim(value: int, multiple: int = 16) -> int:
    """Round down to a positive multiple of ``multiple`` (Wan / VAE friendly)."""
    v = int(value)
    if v < multiple:
        return multiple
    return (v // multiple) * multiple


def clamp_wan_length(
    requested: int,
    *,
    remaining: int | None = None,
    max_length: int = MAX_CHUNK_LENGTH,
) -> int:
    """Clamp to max chunk size, remaining frames, and Wan step-4 lengths (1,5,9,…)."""
    n = min(int(requested), int(max_length))
    if remaining is not None:
        n = min(n, max(0, int(remaining)))
    if n <= 0:
        return 0
    # Schema step=4 with default 77 → valid values 1 + 4k
    aligned = ((n - 1) // 4) * 4 + 1
    return max(1, aligned)


def next_video_frame_offset(offset: int, length: int) -> int:
    """Driving-frame index to pass on the next Extend (absolute, before Comfy subtract)."""
    return max(0, int(offset)) + max(0, int(length))


def probe_video_meta(path: str | Path) -> tuple[float | None, int | None]:
    """Return (fps, frame_count) via ffprobe when available."""
    src = Path(path)
    if not src.is_file():
        return None, None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None
    try:
        # fps from stream
        r = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate,nb_frames,duration",
                "-of",
                "json",
                str(src),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None, None
        st = streams[0]
        fps: float | None = None
        rate = str(st.get("r_frame_rate") or "").strip()
        if rate and rate != "0/0" and "/" in rate:
            num_s, den_s = rate.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den > 0:
                fps = num / den
        frames: int | None = None
        nb = st.get("nb_frames")
        if nb not in (None, "N/A", ""):
            frames = int(nb)
        elif fps and st.get("duration") not in (None, "N/A", ""):
            frames = max(1, int(round(float(st["duration"]) * fps)))
        return fps, frames
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError, KeyError):
        return None, None


def patch_wan_animate_workflow(
    workflow: dict[str, Any],
    *,
    character_ref: str,
    video_ref: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    seed: int,
    steps: int,
    cfg: float,
    fps: float,
    lora_strength: float,
    shift: float,
    video_frame_offset: int = 0,
    continue_motion_max_frames: int = DEFAULT_CONTINUE_MOTION_MAX_FRAMES,
    continue_motion_ref: str | None = None,
    vitpose_model: str = VITPOSE_NAME,
    yolo_model: str = YOLO_NAME,
    onnx_device: str = "CUDAExecutionProvider",
) -> dict[str, Any]:
    """Patch API-format graph inputs for a wan_animate Animation-mode run."""
    w = copy.deepcopy(workflow)
    width = align_dim(width)
    height = align_dim(height)
    length = max(1, int(length))
    offset = max(0, int(video_frame_offset))
    cm_max = max(1, int(continue_motion_max_frames))

    w["1"]["inputs"]["unet_name"] = DIFFUSION_NAME
    w["5"]["inputs"]["lora_name"] = LORA_NAME
    w["5"]["inputs"]["strength_model"] = float(lora_strength)
    w["6"]["inputs"]["shift"] = float(shift)

    w["7"]["inputs"]["text"] = prompt
    w["8"]["inputs"]["text"] = negative_prompt

    w["9"]["inputs"]["image"] = character_ref
    w["11"]["inputs"]["file"] = video_ref

    w["13"]["inputs"]["vitpose_model"] = vitpose_model
    w["13"]["inputs"]["yolo_model"] = yolo_model
    w["13"]["inputs"]["onnx_device"] = onnx_device

    for node_id in ("14", "15", "16"):
        w[node_id]["inputs"]["width"] = width
        w[node_id]["inputs"]["height"] = height

    w["16"]["inputs"]["length"] = length
    w["16"]["inputs"]["video_frame_offset"] = offset
    w["16"]["inputs"]["continue_motion_max_frames"] = cm_max

    if continue_motion_ref:
        w["22"] = {
            "class_type": "LoadVideo",
            "inputs": {"file": continue_motion_ref},
        }
        w["23"] = {
            "class_type": "GetVideoComponents",
            "inputs": {"video": ["22", 0]},
        }
        # Last N frames: negative batch_index wraps from end.
        w["24"] = {
            "class_type": "ImageFromBatch",
            "inputs": {
                "image": ["23", 0],
                "batch_index": -cm_max,
                "length": cm_max,
            },
        }
        w["16"]["inputs"]["continue_motion"] = ["24", 0]
    else:
        w["16"]["inputs"].pop("continue_motion", None)
        for nid in ("22", "23", "24"):
            w.pop(nid, None)

    w["18"]["inputs"]["seed"] = int(seed)
    w["18"]["inputs"]["steps"] = int(steps)
    w["18"]["inputs"]["cfg"] = float(cfg)

    w["20"]["inputs"]["fps"] = float(fps)
    return w


class WanAnimatePipeline(Pipeline):
    """Drive a pose-locked character still with motion from a reference video."""

    id = "wan_animate"
    domain = "video"

    def validate(
        self,
        *,
        character_image: str | Path | None = None,
        driving_video: str | Path | None = None,
        prompt: str = "",
        **kwargs: Any,
    ) -> None:
        if not character_image or not Path(character_image).is_file():
            raise ValueError(
                "character_image is required and must be an existing file"
            )
        if not driving_video or not Path(driving_video).is_file():
            raise ValueError(
                "driving_video is required and must be an existing file"
            )
        if prompt is not None and not isinstance(prompt, str):
            raise ValueError("prompt must be a string when provided")
        cont = kwargs.get("continue_motion")
        if cont is not None and cont != "" and not Path(cont).is_file():
            raise ValueError("continue_motion must be an existing file when provided")

    def run(
        self,
        *,
        character_image: str | Path,
        driving_video: str | Path,
        prompt: str = DEFAULT_PROMPT,
        negative_prompt: str = DEFAULT_NEGATIVE,
        width: int = 832,
        height: int = 480,
        length: int = MAX_CHUNK_LENGTH,
        seed: int | None = None,
        steps: int = 4,
        cfg: float = 1.0,
        fps: float | None = None,
        lora_strength: float = 1.0,
        shift: float = 8.0,
        video_frame_offset: int = 0,
        continue_motion: str | Path | None = None,
        continue_motion_max_frames: int = DEFAULT_CONTINUE_MOTION_MAX_FRAMES,
        driving_frame_count: int | None = None,
        onnx_device: str = "CUDAExecutionProvider",
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        self.validate(
            character_image=character_image,
            driving_video=driving_video,
            prompt=prompt,
            continue_motion=continue_motion,
        )
        settings = get_settings()
        base = comfy_url or getattr(settings, "comfy_url", "http://127.0.0.1:8188")
        client = ComfyClient(base_url=base)

        if not client.health():
            raise ComfyClientError(
                f"ComfyUI not reachable at {base}. Start it with:\n"
                "  cd runtime/comfyui && python main.py --listen 127.0.0.1 --port 8188 "
                "--extra-model-paths-config ../../comfyui_extra_model_paths.yaml\n"
                "Ensure ComfyUI-WanAnimatePreprocess is installed under custom_nodes "
                "and Comfy was restarted after install."
            )

        probed_fps, probed_frames = probe_video_meta(driving_video)
        frame_count = (
            int(driving_frame_count)
            if driving_frame_count is not None
            else probed_frames
        )
        offset = max(0, int(video_frame_offset))
        remaining = None
        if frame_count is not None:
            remaining = max(0, int(frame_count) - offset)
        length_val = clamp_wan_length(length, remaining=remaining)
        if length_val <= 0:
            raise ValueError(
                "No remaining driving frames at this offset "
                f"(offset={offset}, driving_frame_count={frame_count})"
            )

        fps_val = float(fps) if fps is not None else None
        if fps_val is None:
            fps_val = float(probed_fps) if probed_fps and probed_fps > 0 else 24.0

        wf = load_workflow_template(WORKFLOW_PATH)
        prompt_graph = {
            k: v for k, v in wf.items() if k != "_meta" and isinstance(v, dict)
        }

        character_ref = client.upload_image(
            character_image, subfolder="photoreal_wan_animate"
        )
        video_ref = client.upload_video(driving_video, subfolder="")
        continue_ref = None
        if continue_motion:
            continue_ref = client.upload_video(continue_motion, subfolder="")

        seed_val = seed if seed is not None else random.randrange(0, 2**32 - 1)

        prompt_graph = patch_wan_animate_workflow(
            prompt_graph,
            character_ref=character_ref,
            video_ref=video_ref,
            prompt=prompt or DEFAULT_PROMPT,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            length=length_val,
            seed=seed_val,
            steps=steps,
            cfg=cfg,
            fps=fps_val,
            lora_strength=lora_strength,
            shift=shift,
            video_frame_offset=offset,
            continue_motion_max_frames=continue_motion_max_frames,
            continue_motion_ref=continue_ref,
            onnx_device=onnx_device,
        )

        out_root = (
            Path(output_dir)
            if output_dir
            else Path(settings.data_root) / "outputs" / "wan_animate"
        )
        out_root.mkdir(parents=True, exist_ok=True)

        media = client.run_workflow(prompt_graph)
        saved: list[Path] = []
        for name, data in media:
            dest = out_root / Path(name).name
            dest.write_bytes(data)
            saved.append(dest)

        next_off = next_video_frame_offset(offset, length_val)
        # When continue_motion is set, Comfy trims overlap frames from the image batch
        # (trim_image ≈ continue_motion_max_frames for typical N).
        trim_image = (
            int(continue_motion_max_frames) if continue_ref else 0
        )
        meta = {
            "pipeline": self.id,
            "mode": "animation",
            "prompt": prompt or DEFAULT_PROMPT,
            "negative_prompt": negative_prompt,
            "character_image": str(Path(character_image).resolve()),
            "driving_video": str(Path(driving_video).resolve()),
            "continue_motion": (
                str(Path(continue_motion).resolve()) if continue_motion else None
            ),
            "seed": seed_val,
            "width": align_dim(width),
            "height": align_dim(height),
            "length": length_val,
            "video_frame_offset": offset,
            "next_video_frame_offset": next_off,
            "continue_motion_max_frames": int(continue_motion_max_frames),
            "trim_image": trim_image,
            "driving_frame_count": frame_count,
            "steps": steps,
            "cfg": cfg,
            "fps": fps_val,
            "lora_strength": lora_strength,
            "shift": shift,
            "outputs": [str(p) for p in saved],
        }
        if saved:
            (out_root / f"{saved[0].stem}_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        return saved

"""Network Volume layout + completeness checks for Flash character workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

VOLUME_NAME = "photoreal-models"
# Must be accepted by runpod-flash DataCenter AND support network volumes
# on the live Runpod API (SDK/docs can lag). US-KS-2 is in the SDK enum but
# rejected at volume create ("not found or does not support network volumes").
VOLUME_DATACENTER = "US-CA-2"
VOLUME_SIZE_GB = 200
READY_MARKER = ".photoreal_volume_ready"


def flash_datacenter() -> Any:
    """Return ``runpod_flash.DataCenter`` for ``VOLUME_DATACENTER``.

    Raises ``RuntimeError`` with available DCs if the preferred id is missing
    from the installed SDK (so Flash deploy fails with a clear message).
    """
    from runpod_flash import DataCenter

    attr = VOLUME_DATACENTER.replace("-", "_")
    member = getattr(DataCenter, attr, None)
    if member is not None:
        return member
    for dc in DataCenter:
        if getattr(dc, "value", None) == VOLUME_DATACENTER or str(dc) == VOLUME_DATACENTER:
            return dc
    available = [getattr(dc, "value", str(dc)) for dc in DataCenter]
    raise RuntimeError(
        f"runpod-flash DataCenter has no {VOLUME_DATACENTER!r}. "
        f"Update VOLUME_DATACENTER in photoreal.flash.volume_layout. "
        f"Available: {available}"
    )


def volume_root_candidates() -> tuple[Path, ...]:
    """Pod mount is usually /workspace; serverless is /runpod-volume."""
    return (Path("/workspace"), Path("/runpod-volume"))


def resolve_volume_root(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    for cand in volume_root_candidates():
        if cand.is_dir():
            return cand
    return Path("/workspace")


def volume_missing_parts(root: Path | str) -> list[str]:
    """
    Return human-readable reasons the volume is incomplete for character Generate.

    Empty list means models + Comfy layout look complete (size thresholds).
    """
    root = Path(root)
    missing: list[str] = []
    models = root / "data" / "models"
    klein = models / "flux2" / "klein-base-9b"
    loras = models / "loras"
    vlm = models / "vlm" / "Qwen3-VL-8B-Instruct"
    comfy = root / "runtime" / "comfyui" / "main.py"
    yaml = root / "comfyui_extra_model_paths.yaml"

    required_files = (
        (klein / "ae.safetensors", 100_000_000),
        (klein / "flux-2-klein-base-9b.safetensors", 1_000_000_000),
        (klein / "text_encoder" / "qwen_3_8b.safetensors", 1_000_000_000),
        (loras / "lenovo_flux_klein9b.safetensors", 1_000_000),
        (loras / "mrpopo_photorealistic.safetensors", 1_000_000),
    )
    for path, min_bytes in required_files:
        try:
            if not path.is_file() or path.stat().st_size < min_bytes:
                missing.append(f"missing/small: {path.relative_to(root)}")
        except OSError:
            missing.append(f"unreadable: {path.relative_to(root)}")

    te = klein / "text_encoder"
    tok = klein / "tokenizer"
    if not te.is_dir():
        missing.append("missing: data/models/flux2/klein-base-9b/text_encoder/")
    else:
        try:
            if sum(1 for p in te.rglob("*") if p.is_file()) < 3:
                missing.append("incomplete: text_encoder/")
        except OSError:
            missing.append("unreadable: text_encoder/")
    if not tok.is_dir():
        missing.append("missing: data/models/flux2/klein-base-9b/tokenizer/")
    else:
        try:
            if sum(1 for p in tok.rglob("*") if p.is_file()) < 3:
                missing.append("incomplete: tokenizer/")
        except OSError:
            missing.append("unreadable: tokenizer/")

    if not vlm.is_dir():
        missing.append("missing: data/models/vlm/Qwen3-VL-8B-Instruct/")
    else:
        cfg = vlm / "config.json"
        try:
            files = sum(1 for p in vlm.rglob("*") if p.is_file())
        except OSError:
            files = 0
        if not cfg.is_file() or files < 5:
            missing.append("incomplete: VLM Qwen3-VL-8B-Instruct/")

    if not comfy.is_file():
        missing.append("missing: runtime/comfyui/main.py")
    if not yaml.is_file():
        missing.append("missing: comfyui_extra_model_paths.yaml")

    return missing


def volume_models_complete(root: Path | str) -> bool:
    return not volume_missing_parts(root)

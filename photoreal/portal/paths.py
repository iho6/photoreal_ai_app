"""Repo paths for the portal package."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
ENV_PATH = REPO_ROOT / ".env"
LOGS_DIR = REPO_ROOT / "data" / "logs"
COMFY_DIR = REPO_ROOT / "runtime" / "comfyui"
COMFY_REQUIREMENTS = REPO_ROOT / "requirements" / "comfyui-photoreal.txt"
COMFY_EXTRA_LOCAL = REPO_ROOT / "comfyui_extra_model_paths.local.yaml"
COMFY_EXTRA = REPO_ROOT / "comfyui_extra_model_paths.yaml"
DOWNLOAD_SCRIPT = REPO_ROOT / "scripts" / "download_models.py"
VENV_PYTHON_WIN = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYTHON_UNIX = REPO_ROOT / ".venv" / "bin" / "python"

_BASE_PATH_RE = re.compile(r"^\s*base_path:\s*(.+?)\s*$", re.MULTILINE)


def venv_python() -> Path:
    if VENV_PYTHON_WIN.is_file():
        return VENV_PYTHON_WIN
    if VENV_PYTHON_UNIX.is_file():
        return VENV_PYTHON_UNIX
    return Path("python")


def write_comfy_extra_local_yaml(
    repo_root: Path | None = None,
    *,
    out: Path | None = None,
) -> Path:
    """Write ``comfyui_extra_model_paths.local.yaml`` with absolute ``data/`` paths."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    data = (root / "data").resolve()
    out_path = out if out is not None else (root / "comfyui_extra_model_paths.local.yaml")
    out_path.write_text(
        f"""# Auto-generated — local absolute paths
# Use: python main.py --extra-model-paths-config {out_path.as_posix()}

photoreal_data:
  base_path: {data.as_posix()}/
  checkpoints: models/flux2/klein-base-9b/
  unet: models/flux2/klein-base-9b/
  diffusion_models: models/flux2/klein-base-9b/
  vae: models/flux2/klein-base-9b/
  text_encoders: models/flux2/klein-base-9b/text_encoder/
  clip: models/flux2/klein-base-9b/text_encoder/
  loras: models/loras/
  embeddings: models/embeddings/

photoreal_sam3:
  base_path: {data.as_posix()}/
  checkpoints: models/sam3/

photoreal_depth:
  base_path: {data.as_posix()}/
  geometry_estimation: models/depth_anything3/

photoreal_wan:
  base_path: {data.as_posix()}/
  diffusion_models: models/wan/diffusion_models/
  text_encoders: models/wan/text_encoders/
  vae: models/wan/vae/
  clip_vision: models/wan/clip_vision/
  loras: models/wan/loras/
  detection: models/wan/detection/
""",
        encoding="utf-8",
    )
    return out_path


def _yaml_base_paths_match_data(yaml_text: str, expected_data: Path) -> bool:
    """True if every ``base_path`` in the YAML resolves to ``expected_data``."""
    matches = _BASE_PATH_RE.findall(yaml_text)
    if not matches:
        return False
    expected = expected_data.resolve()
    for raw in matches:
        value = raw.strip().strip("\"'")
        if not value:
            return False
        try:
            if Path(value).resolve() != expected:
                return False
        except OSError:
            return False
    return True


def ensure_comfy_extra_local(
    *,
    log: Callable[[str], None] | None = None,
) -> Path:
    """
    Ensure ``comfyui_extra_model_paths.local.yaml`` points at this repo's ``data/``.

    Rewrites when missing or when ``base_path`` is stale (e.g. drive letter moved).
    """
    expected_data = (REPO_ROOT / "data").resolve()
    out = COMFY_EXTRA_LOCAL
    needs_write = True
    if out.is_file():
        try:
            text = out.read_text(encoding="utf-8")
            needs_write = not _yaml_base_paths_match_data(text, expected_data)
        except OSError:
            needs_write = True
    if needs_write:
        write_comfy_extra_local_yaml(REPO_ROOT, out=out)
        msg = f"comfy paths: rewrote .local.yaml -> {expected_data.as_posix()}/"
        if log:
            log(msg)
        else:
            print(msg)
    return out


def comfy_extra_config() -> Path:
    """Prefer healed local absolute paths; fall back to relative template."""
    try:
        return ensure_comfy_extra_local()
    except OSError:
        if COMFY_EXTRA_LOCAL.is_file():
            return COMFY_EXTRA_LOCAL
        return COMFY_EXTRA

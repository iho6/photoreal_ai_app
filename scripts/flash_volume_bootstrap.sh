#!/usr/bin/env bash
# Populate / check Runpod Network Volume for Flash character workers.
# Runs on a short-lived pod with the volume mounted at /workspace (or /runpod-volume).
# Embedded payloads (download_models.py, yaml, volume_layout check) are written by
# photoreal.flash.volume_sync before start — see /tmp/photoreal_sync_payload/.
set -euo pipefail

VOL="${PHOTOREAL_VOLUME_ROOT:-}"
if [[ -z "$VOL" ]]; then
  if [[ -d /workspace ]]; then
    VOL=/workspace
  elif [[ -d /runpod-volume ]]; then
    VOL=/runpod-volume
  else
    VOL=/workspace
  fi
fi
export PHOTOREAL_VOLUME_ROOT="$VOL"
FORCE="${PHOTOREAL_FORCE_SYNC:-0}"
PAYLOAD="${PHOTOREAL_SYNC_PAYLOAD:-/tmp/photoreal_sync_payload}"
WORK=/tmp/photoreal_sync_work

echo "=== photoreal volume sync ==="
echo "volume_root=$VOL force=$FORCE"

mkdir -p "$VOL" "$WORK"
# Persist progress on the volume (and keep stdout for Runpod SSE when available).
if command -v tee >/dev/null 2>&1; then
  exec > >(tee -a "$VOL/photoreal_sync.log") 2>&1
fi
echo "=== photoreal volume sync $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "volume_root=$VOL force=$FORCE"

check_complete() {
  python3 - <<'PY'
from pathlib import Path
import os, sys
sys.path.insert(0, os.environ.get("PHOTOREAL_SYNC_PAYLOAD", "/tmp/photoreal_sync_payload"))
from volume_layout import volume_missing_parts, volume_models_complete
root = Path(os.environ["PHOTOREAL_VOLUME_ROOT"])
missing = volume_missing_parts(root)
if missing:
    print("INCOMPLETE:")
    for m in missing:
        print(f"  - {m}")
    sys.exit(1)
print("COMPLETE: volume models + Comfy layout OK")
sys.exit(0)
PY
}

if [[ "$FORCE" != "1" ]] && check_complete; then
  touch "$VOL/.photoreal_volume_ready"
  echo "PHOTOREAL_VOLUME_SYNC_OK already_complete"
  exit 0
fi

echo "Volume incomplete or force=1 — downloading…"

# Payload must include download_models.py, flash_comfyui_extra_model_paths.yaml, volume_layout.py
if [[ ! -f "$PAYLOAD/download_models.py" ]]; then
  echo "ERROR: missing $PAYLOAD/download_models.py (sync orchestrator should embed it)" >&2
  echo "PHOTOREAL_VOLUME_SYNC_FAIL missing_payload"
  exit 2
fi

# Fake repo layout matching local scripts/download_models.py (parents[1] = repo root).
# Older flat copy wrote to /tmp/photoreal_sync_work/data (container disk) and filled it.
mkdir -p "$VOL/data" "$VOL/.cache/huggingface" "$WORK/repo/scripts"
cp -f "$PAYLOAD/download_models.py" "$WORK/repo/scripts/download_models.py"
cp -f "$PAYLOAD/volume_layout.py" "$WORK/repo/volume_layout.py" 2>/dev/null || true
cp -f "$PAYLOAD/flash_comfyui_extra_model_paths.yaml" \
  "$WORK/repo/flash_comfyui_extra_model_paths.yaml" 2>/dev/null || true
rm -rf "$WORK/repo/data" "$WORK/data"
ln -sfn "$VOL/data" "$WORK/repo/data"
# Belt-and-suspenders if an old script still resolves REPO_ROOT to $WORK
ln -sfn "$VOL/data" "$WORK/data"

python3 -m pip install -q --upgrade pip
python3 -m pip install -q 'huggingface_hub>=0.24' 'tqdm' 'httpx' 'safetensors'

cd "$WORK/repo"
export PHOTOREAL_REPO_ROOT="$WORK/repo"
export PHOTOREAL_MODELS_ROOT="$VOL/data/models"
export HF_HOME="$VOL/.cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$HF_HOME"
export HF_TOKEN="${HF_TOKEN:-}"
export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
export CIVITAI_API_TOKEN="${CIVITAI_API_TOKEN:-}"
echo "download target models_root=$PHOTOREAL_MODELS_ROOT hf_home=$HF_HOME"
df -h "$VOL" /tmp 2>/dev/null || true
python3 scripts/download_models.py --all

# ComfyUI checkout on the volume
COMFY="$VOL/runtime/comfyui"
if [[ ! -f "$COMFY/main.py" ]]; then
  echo "Cloning ComfyUI into $COMFY…"
  mkdir -p "$VOL/runtime"
  rm -rf "$COMFY"
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
fi

YAML_SRC="$PAYLOAD/flash_comfyui_extra_model_paths.yaml"
if [[ -f "$YAML_SRC" ]]; then
  cp -f "$YAML_SRC" "$VOL/comfyui_extra_model_paths.yaml"
fi

if ! check_complete; then
  echo "PHOTOREAL_VOLUME_SYNC_FAIL still_incomplete_after_download"
  exit 1
fi

touch "$VOL/.photoreal_volume_ready"
echo "PHOTOREAL_VOLUME_SYNC_OK"
exit 0

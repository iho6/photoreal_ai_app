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

mkdir -p "$VOL/data" "$WORK/repo"
cp -a "$PAYLOAD/." "$WORK/repo/"
# download_models writes to <repo>/data/models — point that at the volume
rm -rf "$WORK/repo/data"
ln -sfn "$VOL/data" "$WORK/repo/data"

python3 -m pip install -q --upgrade pip
python3 -m pip install -q 'huggingface_hub>=0.24' 'tqdm' 'httpx' 'safetensors'

cd "$WORK/repo"
export HF_TOKEN="${HF_TOKEN:-}"
export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
export CIVITAI_API_TOKEN="${CIVITAI_API_TOKEN:-}"
python3 download_models.py --all

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

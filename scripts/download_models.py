#!/usr/bin/env python3
"""Download model weights for photoreal abilities.

One entrypoint; select abilities with CLI flags.

Requires (for gated HF assets):
  HF_TOKEN — Hugging Face token after accepting FLUX Non-Commercial licenses
  CIVITAI_API_TOKEN — optional; helps with Civitai rate limits

Usage (from repo root):
  python scripts/download_models.py --photoreal-gen
  python scripts/download_models.py --photoreal-gen --with-snofs
  python scripts/download_models.py --vlm
  python scripts/download_models.py --all
  python scripts/download_models.py --all --loras-only
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = REPO_ROOT / "data" / "models"
KLEIN_DIR = MODELS_ROOT / "flux2" / "klein-base-9b"
LORAS_DIR = MODELS_ROOT / "loras"
OPTIONAL_LORAS_DIR = LORAS_DIR / "optional"

# Ability ids (CLI flags use dashes: --photoreal-gen, --vlm)
ABILITIES = ("photoreal_gen", "vlm")

HF_VLM_REPO = "Qwen/Qwen3-VL-8B-Instruct"
VLM_DIR = MODELS_ROOT / "vlm" / "Qwen3-VL-8B-Instruct"

# Hugging Face (gated — NC license)
HF_KLEIN_REPO = "black-forest-labs/FLUX.2-klein-base-9B"
HF_AE_REPO = "black-forest-labs/FLUX.2-dev"
HF_AE_FILE = "ae.safetensors"
HF_KLEIN_TRANSFORMER_FILE = "flux-2-klein-base-9b.safetensors"
HF_TE_PREFIX = "text_encoder"
HF_TOKENIZER_PREFIX = "tokenizer"

CIVITAI_LENOVO = {
    "version_id": 2682771,
    "filename": "lenovo_flux_klein9b.safetensors",
    "url": "https://civitai.com/api/download/models/2682771",
    "role": "lenovo_ultrareal",
}
CIVITAI_MRPOPO = {
    "version_id": 2972219,
    "filename": "mrpopo_photorealistic.safetensors",
    "url": "https://civitai.com/api/download/models/2972219",
    "role": "mrpopo_photoreal",
}
CIVITAI_SNOFS = {
    "version_id": 2695876,
    "filename": "klein_snofs_v1_1.safetensors",
    "url": "https://civitai.com/api/download/models/2695876",
    "role": "snofs_optional_nsfw",
}


def _hf_token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _civitai_token() -> str | None:
    return os.environ.get("CIVITAI_API_TOKEN") or os.environ.get("CIVITAI_TOKEN")


def download_civitai(entry: dict, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip (exists): {dest}")
        return {"path": str(dest.relative_to(REPO_ROOT)), "skipped": True, **entry}

    headers = {"User-Agent": "photoreal_ai_app/0.1"}
    token = _civitai_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(entry["url"], headers=headers)
    print(f"  downloading Civitai {entry['role']} -> {dest.name}")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Civitai download failed for {entry['role']} "
            f"(HTTP {e.code}). Set CIVITAI_API_TOKEN if rate-limited.\n{e}"
        ) from e

    dest.write_bytes(data)
    print(f"  wrote {dest} ({len(data)} bytes)")
    return {
        "path": str(dest.relative_to(REPO_ROOT)),
        "bytes": len(data),
        "skipped": False,
        **entry,
    }


def download_hf_klein_stack(*, transformer: bool, text_stack: bool) -> list[dict]:
    token = _hf_token()
    if not token:
        raise SystemExit(
            "HF_TOKEN is required to download gated FLUX.2 Klein 9B Base / AE.\n"
            "1) Create a token at https://huggingface.co/settings/tokens\n"
            "2) Accept the FLUX Non-Commercial license on:\n"
            f"   https://huggingface.co/{HF_KLEIN_REPO}\n"
            f"   https://huggingface.co/{HF_AE_REPO}\n"
            "3) export HF_TOKEN=...\n"
        )

    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install -e '.[photoreal-gen]'"
        ) from e

    results: list[dict] = []
    KLEIN_DIR.mkdir(parents=True, exist_ok=True)

    ae_path = Path(
        hf_hub_download(
            repo_id=HF_AE_REPO,
            filename=HF_AE_FILE,
            local_dir=str(KLEIN_DIR),
            token=token,
        )
    )
    target_ae = KLEIN_DIR / HF_AE_FILE
    if ae_path.resolve() != target_ae.resolve() and ae_path.exists():
        target_ae.write_bytes(ae_path.read_bytes())
    results.append(
        {
            "role": "flux2_ae",
            "repo": HF_AE_REPO,
            "file": HF_AE_FILE,
            "path": str(target_ae.relative_to(REPO_ROOT)),
            "license": "FLUX / check ae card — do not download flux2-dev.safetensors",
        }
    )
    print(f"  AE -> {target_ae}")

    if transformer:
        try:
            t_path = Path(
                hf_hub_download(
                    repo_id=HF_KLEIN_REPO,
                    filename=HF_KLEIN_TRANSFORMER_FILE,
                    local_dir=str(KLEIN_DIR),
                    token=token,
                )
            )
            target_t = KLEIN_DIR / HF_KLEIN_TRANSFORMER_FILE
            if t_path.resolve() != target_t.resolve() and t_path.exists():
                if not target_t.exists():
                    target_t.write_bytes(t_path.read_bytes())
            results.append(
                {
                    "role": "klein_base_9b_transformer",
                    "repo": HF_KLEIN_REPO,
                    "file": HF_KLEIN_TRANSFORMER_FILE,
                    "path": str(target_t.relative_to(REPO_ROOT)),
                    "license": "FLUX Non-Commercial",
                }
            )
            print(f"  transformer -> {target_t}")
        except Exception as e:
            print(
                f"  single-file transformer download failed ({e}); "
                "falling back to Diffusers transformer/ snapshot"
            )
            snap = snapshot_download(
                repo_id=HF_KLEIN_REPO,
                allow_patterns=["transformer/*", "model_index.json"],
                local_dir=str(KLEIN_DIR / "diffusers_snapshot"),
                token=token,
            )
            results.append(
                {
                    "role": "klein_base_9b_transformer_shards",
                    "repo": HF_KLEIN_REPO,
                    "path": str(Path(snap).relative_to(REPO_ROOT)),
                    "license": "FLUX Non-Commercial",
                }
            )

    if text_stack:
        te_dir = KLEIN_DIR / "text_encoder"
        tok_dir = KLEIN_DIR / "tokenizer"
        snap = snapshot_download(
            repo_id=HF_KLEIN_REPO,
            allow_patterns=[f"{HF_TE_PREFIX}/*", f"{HF_TOKENIZER_PREFIX}/*"],
            local_dir=str(KLEIN_DIR / "diffusers_te_tok"),
            token=token,
        )
        snap_path = Path(snap)
        src_te = snap_path / HF_TE_PREFIX
        src_tok = snap_path / HF_TOKENIZER_PREFIX
        if src_te.is_dir():
            te_dir.mkdir(parents=True, exist_ok=True)
            for p in src_te.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(src_te)
                    out = te_dir / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists():
                        out.write_bytes(p.read_bytes())
        if src_tok.is_dir():
            tok_dir.mkdir(parents=True, exist_ok=True)
            for p in src_tok.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(src_tok)
                    out = tok_dir / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists():
                        out.write_bytes(p.read_bytes())
        results.append(
            {
                "role": "qwen3_text_encoder_and_tokenizer",
                "repo": HF_KLEIN_REPO,
                "path": str(KLEIN_DIR.relative_to(REPO_ROOT)),
                "license": "bundled with Klein base (gated)",
            }
        )
        print(f"  text_encoder/tokenizer under {KLEIN_DIR}")

    return results


def _write_local_comfy_paths() -> None:
    data = (REPO_ROOT / "data").resolve()
    out = REPO_ROOT / "comfyui_extra_model_paths.local.yaml"
    out.write_text(
        f"""# Auto-generated by scripts/download_models.py — local absolute paths
# Use: python main.py --extra-model-paths-config {out.as_posix()}

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
""",
        encoding="utf-8",
    )
    print(f"Wrote {out}")


def download_photoreal_gen(
    *,
    with_snofs: bool = False,
    loras_only: bool = False,
    hf_only: bool = False,
) -> dict:
    """Download weights for the photoreal_gen ability."""
    records: dict = {
        "ability": "photoreal_gen",
        "backbone": "flux.2-klein-base-9b",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "assets": [],
        "notes": [
            "Klein 9B Base is FLUX Non-Commercial (gated on Hugging Face).",
            "Do not download full FLUX.2 [dev] transformer.",
            "Default SFW LoRAs: Lenovo UltraReal + Mrpopo photoreal.",
        ],
    }

    if not loras_only:
        print("[photoreal_gen] Hugging Face Klein 9B Base stack...")
        records["assets"].extend(
            download_hf_klein_stack(transformer=True, text_stack=True)
        )

    if not hf_only:
        print("[photoreal_gen] Civitai LoRAs...")
        records["assets"].append(
            download_civitai(CIVITAI_LENOVO, LORAS_DIR / CIVITAI_LENOVO["filename"])
        )
        records["assets"].append(
            download_civitai(CIVITAI_MRPOPO, LORAS_DIR / CIVITAI_MRPOPO["filename"])
        )
        if with_snofs:
            records["assets"].append(
                download_civitai(
                    CIVITAI_SNOFS, OPTIONAL_LORAS_DIR / CIVITAI_SNOFS["filename"]
                )
            )

    te_flat = KLEIN_DIR / "text_encoder" / "qwen_3_8b.safetensors"
    if not te_flat.exists():
        records["notes"].append(
            "Create data/models/flux2/klein-base-9b/text_encoder/qwen_3_8b.safetensors "
            "for Comfy CLIPLoader (type=flux2)."
        )
        print(
            "NOTE: Place qwen_3_8b.safetensors under "
            f"{te_flat.parent} for CLIPLoader (see docs/photoreal_gen.md)."
        )

    _write_local_comfy_paths()
    manifest = MODELS_ROOT / "photoreal_gen_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


def download_vlm() -> dict:
    """Snapshot Qwen3-VL-8B-Instruct into data/models/vlm/."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install -e '.[vlm]' (or .[photoreal-gen])"
        ) from e

    print(f"=== vlm: {HF_VLM_REPO} ===")
    VLM_DIR.mkdir(parents=True, exist_ok=True)
    token = _hf_token()  # optional; Qwen3-VL is typically public
    snap = snapshot_download(
        repo_id=HF_VLM_REPO,
        local_dir=str(VLM_DIR),
        token=token,
    )
    records = {
        "ability": "vlm",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "repo": HF_VLM_REPO,
        "path": str(Path(snap).resolve().relative_to(REPO_ROOT)),
        "notes": [
            "Qwen3-VL-8B-Instruct ~19 GB BF16; run sequentially vs Klein 9B on 24 GB VRAM.",
            "Install: pip install -e '.[vlm]'",
        ],
    }
    manifest = MODELS_ROOT / "vlm_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


# Register ability download callables here as new abilities are added.
ABILITY_DOWNLOADERS = {
    "photoreal_gen": download_photoreal_gen,
    "vlm": download_vlm,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download model weights for photoreal abilities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Abilities:\n"
            "  --photoreal-gen   FLUX.2 Klein 9B Base + Lenovo + Mrpopo LoRAs\n"
            "  --vlm             Qwen3-VL-8B-Instruct (multimodal)\n"
            "  --all             Every registered ability\n"
        ),
    )
    ability = parser.add_argument_group("abilities (pick one or more, or --all)")
    ability.add_argument(
        "--photoreal-gen",
        action="store_true",
        help="Download models for photoreal_gen",
    )
    ability.add_argument(
        "--vlm",
        action="store_true",
        help="Download Qwen3-VL-8B-Instruct for vlm / reprompt",
    )
    ability.add_argument(
        "--all",
        action="store_true",
        help="Download models for all abilities",
    )

    opts = parser.add_argument_group("options")
    opts.add_argument(
        "--with-snofs",
        action="store_true",
        help="With --photoreal-gen / --all: also download SNOFS (NSFW optional LoRA)",
    )
    opts.add_argument(
        "--loras-only",
        action="store_true",
        help="Skip Hugging Face base weights; Civitai LoRAs only",
    )
    opts.add_argument(
        "--hf-only",
        action="store_true",
        help="Skip Civitai LoRAs; HF Klein stack only",
    )
    return parser


def selected_abilities(args: argparse.Namespace) -> list[str]:
    if args.all:
        return list(ABILITIES)
    chosen: list[str] = []
    if args.photoreal_gen:
        chosen.append("photoreal_gen")
    if args.vlm:
        chosen.append("vlm")
    return chosen


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    chosen = selected_abilities(args)
    if not chosen:
        parser.error(
            "Select at least one ability flag (e.g. --photoreal-gen, --vlm) or --all"
        )
    if args.loras_only and args.hf_only:
        parser.error("Use only one of --loras-only / --hf-only")

    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Downloading for abilities: {', '.join(chosen)}")

    for ability_id in chosen:
        fn = ABILITY_DOWNLOADERS[ability_id]
        if ability_id == "photoreal_gen":
            fn(
                with_snofs=args.with_snofs,
                loras_only=args.loras_only,
                hf_only=args.hf_only,
            )
        else:
            fn()

    print("Done.")


if __name__ == "__main__":
    main()

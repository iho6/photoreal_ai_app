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
  python scripts/download_models.py --sam3
  python scripts/download_models.py --depth
  python scripts/download_models.py --character-depth
  python scripts/download_models.py --vosk
  python scripts/download_models.py --all
  python scripts/download_models.py --all --loras-only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Prefer PHOTOREAL_REPO_ROOT (Flash volume sync pod); else repo root from scripts/.
_REPO_ENV = (os.environ.get("PHOTOREAL_REPO_ROOT") or "").strip()
REPO_ROOT = Path(_REPO_ENV).resolve() if _REPO_ENV else Path(__file__).resolve().parents[1]
_MODELS_ENV = (os.environ.get("PHOTOREAL_MODELS_ROOT") or "").strip()
MODELS_ROOT = (
    Path(_MODELS_ENV).resolve()
    if _MODELS_ENV
    else REPO_ROOT / "data" / "models"
)
KLEIN_DIR = MODELS_ROOT / "flux2" / "klein-base-9b"
LORAS_DIR = MODELS_ROOT / "loras"
OPTIONAL_LORAS_DIR = LORAS_DIR / "optional"

# Ability ids (CLI flags use dashes: --photoreal-gen, --vlm, --sam3, --depth)
ABILITIES = ("photoreal_gen", "vlm", "sam3", "depth", "character_depth")

HF_VLM_REPO = "Qwen/Qwen3-VL-8B-Instruct"
VLM_DIR = MODELS_ROOT / "vlm" / "Qwen3-VL-8B-Instruct"

# Comfy-Org packaged SAM 3.1 multiplex (used by CheckpointLoaderSimple / SAM3_Detect)
HF_SAM3_REPO = "Comfy-Org/sam3.1"
HF_SAM3_FILE = "checkpoints/sam3.1_multiplex_fp16.safetensors"
SAM3_DIR = MODELS_ROOT / "sam3"
SAM3_CKPT = SAM3_DIR / "sam3.1_multiplex_fp16.safetensors"

# Depth Anything 3 mono large (geometry_estimation folder type)
HF_DEPTH_REPO = "Comfy-Org/Depth-Anything-3"
HF_DEPTH_FILE = "geometry_estimation/depth_anything_3_mono_large.safetensors"
DEPTH_DIR = MODELS_ROOT / "depth_anything3"
DEPTH_CKPT = DEPTH_DIR / "depth_anything_3_mono_large.safetensors"

# RefControl depth LoRA for character_depth (Klein Base)
HF_REFCONTROL_DEPTH_REPO = "thedeoxen/refcontrol-FLUX.2-klein-9B-reference-depth-lora"
HF_REFCONTROL_DEPTH_FILE = "flux2_klein_9b_refcontrol_depth.safetensors"
REFCONTROL_DEPTH_LORA = LORAS_DIR / HF_REFCONTROL_DEPTH_FILE

# Local Vosk small EN (Record Reference Start/Stop — not an image ability)
VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOSK_ZIP_URL = (
    f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"
)
VOSK_DIR = MODELS_ROOT / "vosk"
VOSK_MODEL_DIR = VOSK_DIR / VOSK_MODEL_NAME

# Hugging Face (gated — NC license)
HF_KLEIN_REPO = "black-forest-labs/FLUX.2-klein-base-9B"
HF_AE_REPO = "black-forest-labs/FLUX.2-dev"
HF_AE_FILE = "ae.safetensors"
HF_KLEIN_TRANSFORMER_FILE = "flux-2-klein-base-9b.safetensors"
HF_TE_PREFIX = "text_encoder"
HF_TOKENIZER_PREFIX = "tokenizer"


def portal_tqdm_class() -> Any:
    """
    Subclass of huggingface_hub tqdm that keeps HF internals (format_dict, etc.)
    but emits ``@@PROGRESS@@|<pct>|<label>`` lines for the portal.
    """
    from huggingface_hub.utils.tqdm import tqdm as HfTqdm

    class PortalTqdm(HfTqdm):
        _portal_last_emit = 0.0
        _portal_last_key = ""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # Avoid rendering the real ANSI bar into the piped log.
            kwargs.setdefault("leave", False)
            kwargs.setdefault("dynamic_ncols", False)
            super().__init__(*args, **kwargs)
            self._portal_last_pct = -1.0

        def display(self, msg: Any = None, pos: Any = None, **kwargs: Any) -> Any:
            # Skip default status_printer output; we emit a portal marker instead.
            self._portal_emit()
            return True

        def update(self, n: float | int = 1) -> Any:
            result = super().update(n)
            self._portal_emit()
            return result

        def refresh(self, nolock: bool = False, lock_args: Any = None) -> Any:
            result = super().refresh(nolock=nolock, lock_args=lock_args)
            self._portal_emit()
            return result

        def set_postfix_str(self, s: str = "", refresh: bool = True) -> None:
            super().set_postfix_str(s, refresh=False)
            if refresh:
                self._portal_emit()

        def close(self) -> None:
            try:
                self._portal_emit(force=True)
            finally:
                # Prevent parent close from printing a leftover bar line.
                try:
                    self.disable = True
                except Exception:  # noqa: BLE001
                    pass
                super().close()

        def _portal_emit(self, force: bool = False) -> None:
            if getattr(self, "disable", False):
                return
            total = getattr(self, "total", None) or 0
            n = int(getattr(self, "n", 0) or 0)
            desc = str(getattr(self, "desc", None) or "download").strip() or "download"

            # Snapshot creates two bars; prefer the byte-download bar for %.
            # Still allow reconstruction bar if it's the only one moving.
            low = desc.lower()
            if "reconstruct" in low and total and n <= 0 and not force:
                return

            if total and float(total) > 0:
                pct = 100.0 * min(float(n), float(total)) / float(total)
            else:
                pct = 0.0

            now = time.monotonic()
            key = f"{desc}|{int(pct * 10)}|{n}"
            if (
                not force
                and key == PortalTqdm._portal_last_key
                and now - PortalTqdm._portal_last_emit < 0.25
            ):
                return
            if (
                not force
                and now - PortalTqdm._portal_last_emit < 0.2
                and abs(pct - self._portal_last_pct) < 0.05
                and "download" not in low
            ):
                return

            PortalTqdm._portal_last_emit = now
            PortalTqdm._portal_last_key = key
            self._portal_last_pct = pct

            if total and float(total) > 0:
                if float(total) >= 1_000_000:
                    label = f"{desc} ({n}/{int(total)})"
                else:
                    label = f"{desc} ({n}/{int(total)})"
            else:
                label = f"{desc} ({n})"

            # More precision while still near 0% on multi-GB files.
            pct_s = f"{pct:.2f}" if pct < 1.0 else f"{pct:.1f}"
            print(f"@@PROGRESS@@|{pct_s}|{label}", flush=True)

    return PortalTqdm


def _enable_portal_hf_progress() -> Any:
    from huggingface_hub.utils import enable_progress_bars

    enable_progress_bars()
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"
    return portal_tqdm_class()


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

# LoRAs are multi‑MB; reject tiny placeholders even if size probe fails.
_CIVITAI_MIN_BYTES = 1_000_000


def _hf_token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _civitai_token() -> str | None:
    return os.environ.get("CIVITAI_API_TOKEN") or os.environ.get("CIVITAI_TOKEN")


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _sizes_match(local_bytes: int, expected_bytes: int, *, tol: int = 0) -> bool:
    return local_bytes > 0 and abs(local_bytes - expected_bytes) <= tol


def _civitai_headers() -> dict[str, str]:
    headers = {"User-Agent": "photoreal_ai_app/0.1"}
    token = _civitai_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def civitai_expected_bytes(entry: dict) -> int | None:
    """
    Resolve expected download size for a Civitai model version.

    Prefers explicit ``expected_bytes``, then the model-versions API (sizeKB),
    then a HEAD/Range probe on the download URL.
    """
    if entry.get("expected_bytes"):
        try:
            n = int(entry["expected_bytes"])
            return n if n > 0 else None
        except (TypeError, ValueError):
            pass

    version_id = entry.get("version_id")
    headers = _civitai_headers()
    if version_id is not None:
        api = f"https://civitai.com/api/v1/model-versions/{version_id}"
        try:
            req = urllib.request.Request(api, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            files = data.get("files") or []
            want = entry.get("filename")
            chosen = None
            for f in files:
                if want and f.get("name") == want:
                    chosen = f
                    break
                if f.get("primary"):
                    chosen = chosen or f
            if chosen is None and files:
                chosen = files[0]
            if chosen is not None:
                size_kb = chosen.get("sizeKB")
                if size_kb is not None:
                    return max(1, int(round(float(size_kb) * 1024)))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            pass

    url = entry.get("url")
    if not url:
        return None
    # Prefer HEAD; fall back to a 1-byte Range probe (avoids downloading the body).
    probes: list[dict[str, str]] = [
        {**headers},
        {**headers, "Range": "bytes=0-0"},
    ]
    methods = ("HEAD", "GET")
    for method, hdrs in ((methods[0], probes[0]), (methods[1], probes[1])):
        try:
            req = urllib.request.Request(url, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_range = resp.headers.get("Content-Range")
                if content_range and "/" in content_range:
                    total = content_range.rsplit("/", 1)[-1]
                    if total.isdigit() and int(total) > 0:
                        return int(total)
                cl = resp.headers.get("Content-Length")
                if cl and str(cl).isdigit() and int(cl) > 0 and method == "HEAD":
                    return int(cl)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            continue
    return None


def local_file_complete(path: Path, expected_bytes: int | None, *, min_bytes: int = 0) -> bool:
    """True when ``path`` exists and its size matches expected (or passes min_bytes)."""
    size = _file_size(path)
    if size <= 0:
        return False
    if expected_bytes is not None:
        return _sizes_match(size, expected_bytes)
    return size >= min_bytes


def _promote_incomplete_to_partial(dest: Path, tmp: Path) -> int:
    """If dest is incomplete, move it to .partial for resume. Returns partial size."""
    size = _file_size(dest)
    if size <= 0:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return _file_size(tmp)
    if tmp.exists():
        # Keep the larger incomplete blob.
        if _file_size(tmp) >= size:
            dest.unlink(missing_ok=True)
            return _file_size(tmp)
        tmp.unlink(missing_ok=True)
    dest.replace(tmp)
    return size


def download_civitai(entry: dict, dest: Path, *, _retried: bool = False) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = _file_size(dest)
    # Fast path: trust a substantial local file without Civitai HEAD/API.
    if local >= _CIVITAI_MIN_BYTES:
        print(f"  skip (exists, size ok): {dest.name} ({local} bytes)")
        return {
            "path": str(dest.relative_to(REPO_ROOT)),
            "skipped": True,
            "bytes": local,
            "expected_bytes": None,
            **entry,
        }

    expected = civitai_expected_bytes(entry)
    if local_file_complete(dest, expected, min_bytes=_CIVITAI_MIN_BYTES):
        note = f"{local} bytes"
        if expected is not None:
            note = f"{local}/{expected} bytes"
        print(f"  skip (exists, size ok): {dest.name} ({note})")
        return {
            "path": str(dest.relative_to(REPO_ROOT)),
            "skipped": True,
            "bytes": local,
            "expected_bytes": expected,
            **entry,
        }

    tmp = dest.with_suffix(dest.suffix + ".partial")
    if local > 0:
        if expected is not None:
            print(
                f"  incomplete {entry['role']}: local {local} != expected {expected}; "
                "resuming"
            )
        else:
            print(
                f"  incomplete {entry['role']}: local {local} bytes "
                f"(below min {_CIVITAI_MIN_BYTES} or size unverified); resuming"
            )
        existing = _promote_incomplete_to_partial(dest, tmp)
    else:
        if dest.exists():
            dest.unlink()
        existing = _file_size(tmp)

    headers = _civitai_headers()
    if existing > 0:
        # If we somehow already have the full size as partial, finalize.
        if expected is not None and _sizes_match(existing, expected):
            tmp.replace(dest)
            print(f"  finalized partial {dest.name} ({existing} bytes)")
            return {
                "path": str(dest.relative_to(REPO_ROOT)),
                "bytes": existing,
                "skipped": False,
                "expected_bytes": expected,
                **entry,
            }
        headers["Range"] = f"bytes={existing}-"
        print(f"  resuming Civitai {entry['role']} from {existing} bytes -> {dest.name}")
    else:
        print(f"  downloading Civitai {entry['role']} -> {dest.name}")

    req = urllib.request.Request(entry["url"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            # If server ignores Range and returns 200, restart the partial file.
            if existing > 0 and status == 200:
                existing = 0
                print(f"  server ignored Range; restarting {entry['role']}")
            content_range = resp.headers.get("Content-Range")  # bytes start-end/total
            total_n: int | None = expected
            if content_range and "/" in content_range:
                try:
                    total_n = int(content_range.rsplit("/", 1)[-1])
                except ValueError:
                    pass
            if total_n is None:
                cl = resp.headers.get("Content-Length")
                if cl and str(cl).isdigit():
                    # For 206, Content-Length is remaining; for 200 it's full size
                    total_n = int(cl) + (existing if status == 206 else 0)

            wrote = existing
            chunk_size = 1024 * 256
            mode = "ab" if existing > 0 and status == 206 else "wb"
            if mode == "wb" and tmp.exists():
                tmp.unlink()
            last_prog = 0.0

            with open(tmp, mode) as out:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    wrote += len(chunk)
                    now = time.monotonic()
                    if total_n:
                        pct = 100.0 * wrote / total_n
                        if now - last_prog >= 0.25 or pct >= 99.9:
                            last_prog = now
                            print(
                                f"@@PROGRESS@@|{pct:.1f}|{entry['role']} "
                                f"({wrote}/{total_n})",
                                flush=True,
                            )
                    elif now - last_prog >= 0.5:
                        last_prog = now
                        print(
                            f"@@PROGRESS@@|0.0|{entry['role']} ({wrote} bytes)",
                            flush=True,
                        )
            if total_n:
                print(
                    f"@@PROGRESS@@|100.0|{entry['role']} ({wrote}/{total_n})",
                    flush=True,
                )
            if total_n is not None and not _sizes_match(wrote, total_n):
                raise SystemExit(
                    f"Civitai download incomplete for {entry['role']}: "
                    f"got {wrote} bytes, expected {total_n}"
                )
            if wrote < _CIVITAI_MIN_BYTES:
                raise SystemExit(
                    f"Civitai download too small for {entry['role']}: "
                    f"{wrote} bytes (min {_CIVITAI_MIN_BYTES})"
                )
            tmp.replace(dest)
    except urllib.error.HTTPError as e:
        # 416 = partial already complete / bad range — try fresh
        if e.code == 416 and tmp.is_file() and not _retried:
            print(f"  Range rejected for {entry['role']}; removing partial and retrying")
            tmp.unlink(missing_ok=True)
            return download_civitai(entry, dest, _retried=True)
        raise SystemExit(
            f"Civitai download failed for {entry['role']} "
            f"(HTTP {e.code}). Set CIVITAI_API_TOKEN if rate-limited.\n{e}"
        ) from e

    print(f"  wrote {dest} ({wrote} bytes)")
    return {
        "path": str(dest.relative_to(REPO_ROOT)),
        "bytes": wrote,
        "skipped": False,
        "resumed_from": existing if existing > 0 else 0,
        "expected_bytes": total_n if total_n is not None else expected,
        **entry,
    }


def _hf_remote_size(repo_id: str, filename: str, token: str | None) -> int | None:
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url

        meta = get_hf_file_metadata(hf_hub_url(repo_id, filename), token=token)
        size = getattr(meta, "size", None)
        return int(size) if size else None
    except Exception:  # noqa: BLE001 — best-effort probe
        return None


def _hf_local_complete(path: Path, repo_id: str, filename: str, token: str | None) -> bool:
    size = _file_size(path)
    if size <= 0:
        return False
    # Fast path: avoid HF metadata round-trips when the blob is already large.
    # AE ~336MB, transformer ~18GB — anything over 50MB is a real weight file.
    if size >= 50_000_000:
        return True
    expected = _hf_remote_size(repo_id, filename, token)
    if expected is None:
        # Without remote size, still reject empty/tiny stubs.
        return size >= _CIVITAI_MIN_BYTES
    return _sizes_match(size, expected)


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

        tqdm_cls = _enable_portal_hf_progress()
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install -e '.[photoreal-gen]'"
        ) from e

    results: list[dict] = []
    KLEIN_DIR.mkdir(parents=True, exist_ok=True)

    target_ae = KLEIN_DIR / HF_AE_FILE
    if _hf_local_complete(target_ae, HF_AE_REPO, HF_AE_FILE, token):
        print(f"  skip (exists, size ok): {target_ae.name} ({_file_size(target_ae)} bytes)")
        ae_path = target_ae
    else:
        if target_ae.exists() and _file_size(target_ae) > 0:
            print(
                f"  incomplete AE: {_file_size(target_ae)} bytes; re-downloading"
            )
        print("  downloading AE…")
        ae_path = Path(
            hf_hub_download(
                repo_id=HF_AE_REPO,
                filename=HF_AE_FILE,
                local_dir=str(KLEIN_DIR),
                token=token,
                tqdm_class=tqdm_cls,
            )
        )
        if ae_path.resolve() != target_ae.resolve() and ae_path.exists():
            target_ae.write_bytes(ae_path.read_bytes())
        print(f"  AE -> {target_ae} ({_file_size(target_ae)} bytes)")
    results.append(
        {
            "role": "flux2_ae",
            "repo": HF_AE_REPO,
            "file": HF_AE_FILE,
            "path": str(target_ae.relative_to(REPO_ROOT)),
            "bytes": _file_size(target_ae),
            "license": "FLUX / check ae card — do not download flux2-dev.safetensors",
        }
    )

    if transformer:
        target_t = KLEIN_DIR / HF_KLEIN_TRANSFORMER_FILE
        try:
            if _hf_local_complete(
                target_t, HF_KLEIN_REPO, HF_KLEIN_TRANSFORMER_FILE, token
            ):
                print(
                    f"  skip (exists, size ok): {target_t.name} "
                    f"({_file_size(target_t)} bytes)"
                )
            else:
                if target_t.exists() and _file_size(target_t) > 0:
                    print(
                        f"  incomplete transformer: {_file_size(target_t)} bytes; "
                        "re-downloading"
                    )
                print("  downloading transformer…")
                t_path = Path(
                    hf_hub_download(
                        repo_id=HF_KLEIN_REPO,
                        filename=HF_KLEIN_TRANSFORMER_FILE,
                        local_dir=str(KLEIN_DIR),
                        token=token,
                        tqdm_class=tqdm_cls,
                    )
                )
                if t_path.resolve() != target_t.resolve() and t_path.exists():
                    if (
                        not target_t.exists()
                        or _file_size(target_t) != _file_size(t_path)
                    ):
                        target_t.write_bytes(t_path.read_bytes())
                print(f"  transformer -> {target_t} ({_file_size(target_t)} bytes)")
            results.append(
                {
                    "role": "klein_base_9b_transformer",
                    "repo": HF_KLEIN_REPO,
                    "file": HF_KLEIN_TRANSFORMER_FILE,
                    "path": str(target_t.relative_to(REPO_ROOT)),
                    "bytes": _file_size(target_t),
                    "license": "FLUX Non-Commercial",
                }
            )
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
                tqdm_class=tqdm_cls,
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
        te_n = sum(1 for p in te_dir.rglob("*") if p.is_file()) if te_dir.is_dir() else 0
        tok_n = sum(1 for p in tok_dir.rglob("*") if p.is_file()) if tok_dir.is_dir() else 0
        if te_n >= 3 and tok_n >= 3:
            print(
                f"  skip (exists): text_encoder/tokenizer under {KLEIN_DIR} "
                f"({te_n}+{tok_n} files)"
            )
            results.append(
                {
                    "role": "qwen3_text_encoder_and_tokenizer",
                    "repo": HF_KLEIN_REPO,
                    "path": str(KLEIN_DIR.relative_to(REPO_ROOT)),
                    "license": "bundled with Klein base (gated)",
                    "copied_files": 0,
                    "skipped_files": te_n + tok_n,
                }
            )
        else:
            print("  downloading text_encoder/tokenizer…")
            snap = snapshot_download(
                repo_id=HF_KLEIN_REPO,
                allow_patterns=[f"{HF_TE_PREFIX}/*", f"{HF_TOKENIZER_PREFIX}/*"],
                local_dir=str(KLEIN_DIR / "diffusers_te_tok"),
                token=token,
                tqdm_class=tqdm_cls,
            )
            snap_path = Path(snap)
            src_te = snap_path / HF_TE_PREFIX
            src_tok = snap_path / HF_TOKENIZER_PREFIX
            copied = 0
            skipped = 0
            if src_te.is_dir():
                te_dir.mkdir(parents=True, exist_ok=True)
                for p in src_te.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(src_te)
                        out = te_dir / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        src_n = _file_size(p)
                        if out.exists() and _sizes_match(_file_size(out), src_n):
                            skipped += 1
                            continue
                        out.write_bytes(p.read_bytes())
                        copied += 1
            if src_tok.is_dir():
                tok_dir.mkdir(parents=True, exist_ok=True)
                for p in src_tok.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(src_tok)
                        out = tok_dir / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        src_n = _file_size(p)
                        if out.exists() and _sizes_match(_file_size(out), src_n):
                            skipped += 1
                            continue
                        out.write_bytes(p.read_bytes())
                        copied += 1
            results.append(
                {
                    "role": "qwen3_text_encoder_and_tokenizer",
                    "repo": HF_KLEIN_REPO,
                    "path": str(KLEIN_DIR.relative_to(REPO_ROOT)),
                    "license": "bundled with Klein base (gated)",
                    "copied_files": copied,
                    "skipped_files": skipped,
                }
            )
            print(
                f"  text_encoder/tokenizer under {KLEIN_DIR} "
                f"(copied {copied}, size-ok skip {skipped})"
            )

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

photoreal_sam3:
  base_path: {data.as_posix()}/
  checkpoints: models/sam3/

photoreal_depth:
  base_path: {data.as_posix()}/
  geometry_estimation: models/depth_anything3/
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

        tqdm_cls = _enable_portal_hf_progress()
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install -e '.[vlm]' (or .[photoreal-gen])"
        ) from e

    print(f"=== vlm: {HF_VLM_REPO} ===")
    VLM_DIR.mkdir(parents=True, exist_ok=True)
    cfg = VLM_DIR / "config.json"
    weight_bytes = 0
    if VLM_DIR.is_dir():
        for p in VLM_DIR.rglob("*.safetensors"):
            weight_bytes += _file_size(p)
        for p in VLM_DIR.rglob("*.bin"):
            weight_bytes += _file_size(p)
    # ~19GB BF16; treat >= 5GB + config as already present.
    if cfg.is_file() and weight_bytes >= 5_000_000_000:
        print(f"  skip (exists): {VLM_DIR} ({weight_bytes} bytes of weights)")
        records = {
            "ability": "vlm",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_VLM_REPO,
            "path": str(VLM_DIR.resolve().relative_to(REPO_ROOT)),
            "skipped": True,
            "bytes": weight_bytes,
            "notes": [
                "Qwen3-VL-8B-Instruct ~19 GB BF16; run sequentially vs Klein 9B on 24 GB VRAM.",
                "Install: pip install -e '.[vlm]'",
            ],
        }
        manifest = MODELS_ROOT / "vlm_manifest.json"
        manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Wrote manifest {manifest}")
        return records

    print("  downloading VLM weights (large)…")
    token = _hf_token()  # optional; Qwen3-VL is typically public
    snap = snapshot_download(
        repo_id=HF_VLM_REPO,
        local_dir=str(VLM_DIR),
        token=token,
        tqdm_class=tqdm_cls,
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


def download_sam3() -> dict:
    """Download SAM 3.1 multiplex checkpoint for Comfy SAM3_Detect."""
    try:
        from huggingface_hub import hf_hub_download

        tqdm_cls = _enable_portal_hf_progress()
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install huggingface_hub"
        ) from e

    print(f"=== sam3: {HF_SAM3_REPO} / {HF_SAM3_FILE} ===")
    SAM3_DIR.mkdir(parents=True, exist_ok=True)
    token = _hf_token()
    if SAM3_CKPT.is_file() and SAM3_CKPT.stat().st_size >= 50_000_000:
        print(
            f"  skip (exists, size ok): {SAM3_CKPT.name} "
            f"({SAM3_CKPT.stat().st_size} bytes)"
        )
        records = {
            "ability": "sam3",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_SAM3_REPO,
            "file": HF_SAM3_FILE,
            "path": str(SAM3_CKPT.resolve().relative_to(REPO_ROOT)),
            "bytes": SAM3_CKPT.stat().st_size,
            "skipped": True,
            "notes": [
                "Comfy-native SAM 3.1 multiplex checkpoint for sam3_segment.",
                "Accept model terms on Hugging Face if the download is gated.",
            ],
        }
    else:
        print("  downloading SAM 3.1 multiplex checkpoint…")
        downloaded = Path(
            hf_hub_download(
                repo_id=HF_SAM3_REPO,
                filename=HF_SAM3_FILE,
                local_dir=str(SAM3_DIR),
                token=token,
                tqdm_class=tqdm_cls,
            )
        )
        # hf may nest under local_dir/checkpoints/; normalize to flat SAM3_CKPT
        if downloaded.resolve() != SAM3_CKPT.resolve() and downloaded.is_file():
            SAM3_CKPT.parent.mkdir(parents=True, exist_ok=True)
            if SAM3_CKPT.exists():
                SAM3_CKPT.unlink()
            shutil.move(str(downloaded), str(SAM3_CKPT))
        print(f"  SAM3 -> {SAM3_CKPT} ({SAM3_CKPT.stat().st_size} bytes)")
        records = {
            "ability": "sam3",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_SAM3_REPO,
            "file": HF_SAM3_FILE,
            "path": str(SAM3_CKPT.resolve().relative_to(REPO_ROOT)),
            "bytes": SAM3_CKPT.stat().st_size,
            "skipped": False,
            "notes": [
                "Comfy-native SAM 3.1 multiplex checkpoint for sam3_segment.",
                "Accept model terms on Hugging Face if the download is gated.",
            ],
        }

    manifest = MODELS_ROOT / "sam3_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


def download_depth() -> dict:
    """Download Depth Anything 3 mono large for depth_subject."""
    try:
        from huggingface_hub import hf_hub_download

        tqdm_cls = _enable_portal_hf_progress()
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install huggingface_hub"
        ) from e

    print(f"=== depth: {HF_DEPTH_REPO} / {HF_DEPTH_FILE} ===")
    DEPTH_DIR.mkdir(parents=True, exist_ok=True)
    token = _hf_token()
    if DEPTH_CKPT.is_file() and DEPTH_CKPT.stat().st_size >= 50_000_000:
        print(
            f"  skip (exists, size ok): {DEPTH_CKPT.name} "
            f"({DEPTH_CKPT.stat().st_size} bytes)"
        )
        records = {
            "ability": "depth",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_DEPTH_REPO,
            "file": HF_DEPTH_FILE,
            "path": str(DEPTH_CKPT.resolve().relative_to(REPO_ROOT)),
            "bytes": DEPTH_CKPT.stat().st_size,
            "skipped": True,
            "notes": [
                "Comfy-native Depth Anything 3 mono large for depth_subject.",
            ],
        }
    else:
        print("  downloading Depth Anything 3 mono large…")
        downloaded = Path(
            hf_hub_download(
                repo_id=HF_DEPTH_REPO,
                filename=HF_DEPTH_FILE,
                local_dir=str(DEPTH_DIR),
                token=token,
                tqdm_class=tqdm_cls,
            )
        )
        if downloaded.resolve() != DEPTH_CKPT.resolve() and downloaded.is_file():
            DEPTH_CKPT.parent.mkdir(parents=True, exist_ok=True)
            if DEPTH_CKPT.exists():
                DEPTH_CKPT.unlink()
            shutil.move(str(downloaded), str(DEPTH_CKPT))
        print(f"  Depth -> {DEPTH_CKPT} ({DEPTH_CKPT.stat().st_size} bytes)")
        records = {
            "ability": "depth",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_DEPTH_REPO,
            "file": HF_DEPTH_FILE,
            "path": str(DEPTH_CKPT.resolve().relative_to(REPO_ROOT)),
            "bytes": DEPTH_CKPT.stat().st_size,
            "skipped": False,
            "notes": [
                "Comfy-native Depth Anything 3 mono large for depth_subject.",
            ],
        }

    _write_local_comfy_paths()
    manifest = MODELS_ROOT / "depth_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


def download_character_depth() -> dict:
    """Download RefControl depth LoRA for character_depth (Klein Base)."""
    try:
        from huggingface_hub import hf_hub_download

        tqdm_cls = _enable_portal_hf_progress()
    except ImportError as e:
        raise SystemExit(
            "huggingface_hub is required. pip install huggingface_hub"
        ) from e

    print(
        f"=== character_depth: {HF_REFCONTROL_DEPTH_REPO} / "
        f"{HF_REFCONTROL_DEPTH_FILE} ==="
    )
    LORAS_DIR.mkdir(parents=True, exist_ok=True)
    token = _hf_token()
    if (
        REFCONTROL_DEPTH_LORA.is_file()
        and REFCONTROL_DEPTH_LORA.stat().st_size >= 1_000_000
    ):
        print(
            f"  skip (exists, size ok): {REFCONTROL_DEPTH_LORA.name} "
            f"({REFCONTROL_DEPTH_LORA.stat().st_size} bytes)"
        )
        records = {
            "ability": "character_depth",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_REFCONTROL_DEPTH_REPO,
            "file": HF_REFCONTROL_DEPTH_FILE,
            "path": str(REFCONTROL_DEPTH_LORA.resolve().relative_to(REPO_ROOT)),
            "bytes": REFCONTROL_DEPTH_LORA.stat().st_size,
            "skipped": True,
            "notes": [
                "RefControl depth LoRA for character_depth.",
                "Requires Klein Base + Lenovo/Mrpopo from --photoreal-gen.",
            ],
        }
    else:
        print("  downloading RefControl depth LoRA…")
        downloaded = Path(
            hf_hub_download(
                repo_id=HF_REFCONTROL_DEPTH_REPO,
                filename=HF_REFCONTROL_DEPTH_FILE,
                local_dir=str(LORAS_DIR),
                token=token,
                tqdm_class=tqdm_cls,
            )
        )
        if (
            downloaded.resolve() != REFCONTROL_DEPTH_LORA.resolve()
            and downloaded.is_file()
        ):
            if REFCONTROL_DEPTH_LORA.exists():
                REFCONTROL_DEPTH_LORA.unlink()
            shutil.move(str(downloaded), str(REFCONTROL_DEPTH_LORA))
        print(
            f"  RefControl depth -> {REFCONTROL_DEPTH_LORA} "
            f"({REFCONTROL_DEPTH_LORA.stat().st_size} bytes)"
        )
        records = {
            "ability": "character_depth",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "repo": HF_REFCONTROL_DEPTH_REPO,
            "file": HF_REFCONTROL_DEPTH_FILE,
            "path": str(REFCONTROL_DEPTH_LORA.resolve().relative_to(REPO_ROOT)),
            "bytes": REFCONTROL_DEPTH_LORA.stat().st_size,
            "skipped": False,
            "notes": [
                "RefControl depth LoRA for character_depth.",
                "Requires Klein Base + Lenovo/Mrpopo from --photoreal-gen.",
            ],
        }

    _write_local_comfy_paths()
    manifest = MODELS_ROOT / "character_depth_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


def download_vosk() -> dict:
    """Download + unpack Vosk small English model for local voice commands."""
    import io
    import zipfile

    print(f"=== vosk: {VOSK_MODEL_NAME} ===")
    VOSK_DIR.mkdir(parents=True, exist_ok=True)
    if VOSK_MODEL_DIR.is_dir() and any(VOSK_MODEL_DIR.iterdir()):
        print(f"  skip (exists): {VOSK_MODEL_DIR}")
        records = {
            "ability": "vosk",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "url": VOSK_ZIP_URL,
            "path": str(VOSK_MODEL_DIR.resolve().relative_to(REPO_ROOT)),
            "skipped": True,
        }
    else:
        print(f"  downloading {VOSK_ZIP_URL}…")
        req = urllib.request.Request(
            VOSK_ZIP_URL, headers={"User-Agent": "photoreal-download_models"}
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            blob = resp.read()
        print(f"  unpacking ({len(blob)} bytes)…")
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(VOSK_DIR)
        if not VOSK_MODEL_DIR.is_dir():
            raise RuntimeError(
                f"Vosk unpack did not create {VOSK_MODEL_DIR}; "
                f"contents: {list(VOSK_DIR.iterdir())[:10]}"
            )
        print(f"  Vosk -> {VOSK_MODEL_DIR}")
        records = {
            "ability": "vosk",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "url": VOSK_ZIP_URL,
            "path": str(VOSK_MODEL_DIR.resolve().relative_to(REPO_ROOT)),
            "skipped": False,
        }
    manifest = MODELS_ROOT / "vosk_manifest.json"
    manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest}")
    return records


# Register ability download callables here as new abilities are added.
ABILITY_DOWNLOADERS = {
    "photoreal_gen": download_photoreal_gen,
    "vlm": download_vlm,
    "sam3": download_sam3,
    "depth": download_depth,
    "character_depth": download_character_depth,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download model weights for photoreal abilities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Abilities:\n"
            "  --photoreal-gen   FLUX.2 Klein 9B Base + Lenovo + Mrpopo LoRAs\n"
            "  --vlm             Qwen3-VL-8B-Instruct (multimodal)\n"
            "  --sam3            SAM 3.1 multiplex checkpoint (Comfy SAM3_Detect)\n"
            "  --depth           Depth Anything 3 mono large (depth_subject)\n"
            "  --character-depth RefControl depth LoRA (character_depth)\n"
            "  --vosk            Vosk small EN (local Record Reference Start/Stop)\n"
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
        "--sam3",
        action="store_true",
        help="Download SAM 3.1 multiplex checkpoint for sam3_segment",
    )
    ability.add_argument(
        "--depth",
        action="store_true",
        help="Download Depth Anything 3 for depth_subject",
    )
    ability.add_argument(
        "--character-depth",
        action="store_true",
        help="Download RefControl depth LoRA for character_depth",
    )
    ability.add_argument(
        "--all",
        action="store_true",
        help="Download models for all abilities",
    )
    ability.add_argument(
        "--vosk",
        action="store_true",
        help="Download Vosk small English model for local voice commands",
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
    if args.sam3:
        chosen.append("sam3")
    if args.depth:
        chosen.append("depth")
    if args.character_depth:
        chosen.append("character_depth")
    return chosen


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    chosen = selected_abilities(args)
    if not chosen and not args.vosk:
        parser.error(
            "Select at least one ability flag "
            "(e.g. --photoreal-gen, --vlm, --sam3, --depth, --character-depth, "
            "--vosk) or --all"
        )
    if args.loras_only and args.hf_only:
        parser.error("Use only one of --loras-only / --hf-only")

    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    if chosen:
        print(f"Downloading for abilities: {', '.join(chosen)}")
    if args.vosk:
        print("Downloading vosk voice model…")

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
    if args.vosk:
        download_vosk()

    print("Done.")


if __name__ == "__main__":
    main()

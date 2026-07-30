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
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def portal_tqdm_class() -> Any:
    """
    Duck-typed tqdm for huggingface_hub that emits parseable progress lines.

    Uses newline markers (not bare \\r) so progress survives Windows pipes.
    """

    class PortalTqdm:
        def __init__(
            self,
            iterable: Any = None,
            *args: Any,
            total: Any = None,
            desc: Any = None,
            initial: int = 0,
            disable: bool = False,
            **kwargs: Any,
        ) -> None:
            self.iterable = iterable
            self.total = total
            self.n = int(initial or 0)
            self.desc = (desc or kwargs.get("desc") or "") or ""
            self.disable = bool(disable)
            self.leave = bool(kwargs.get("leave", False))
            self.pos = int(kwargs.get("pos") or 0)
            self._last_emit = 0.0
            self._last_pct = -1.0
            if self.iterable is not None and self.total is None:
                try:
                    self.total = len(self.iterable)
                except TypeError:
                    self.total = None

        def __iter__(self):
            if self.iterable is None:
                return iter(())
            for obj in self.iterable:
                yield obj
                self.update(1)
            self.close()

        def __enter__(self) -> "PortalTqdm":
            self._emit(force=True)
            return self

        def __exit__(self, *args: Any) -> None:
            self.close()

        def update(self, n: float | int = 1) -> None:
            if self.disable:
                return
            self.n += int(n)
            self._emit()

        def reset(self, total: Any = None) -> None:
            self.n = 0
            if total is not None:
                self.total = total
            self._emit(force=True)

        def set_description(self, desc: Any = None, refresh: bool = True) -> None:
            if desc is not None:
                self.desc = str(desc)
            if refresh:
                self._emit(force=True)

        def set_description_str(self, desc: Any = None, refresh: bool = True) -> None:
            self.set_description(desc, refresh=refresh)

        def set_postfix(self, *args: Any, **kwargs: Any) -> None:
            return None

        def set_postfix_str(self, *args: Any, **kwargs: Any) -> None:
            return None

        def refresh(self) -> None:
            self._emit(force=True)

        def clear(self) -> None:
            return None

        def close(self) -> None:
            if not self.disable:
                self._emit(force=True)

        def display(self, *args: Any, **kwargs: Any) -> None:
            self._emit(force=True)

        def _emit(self, force: bool = False) -> None:
            if self.disable:
                return
            now = time.monotonic()
            if self.total and float(self.total) > 0:
                pct = 100.0 * min(float(self.n), float(self.total)) / float(self.total)
            else:
                # Unknown total — still heartbeat so UI is not stuck on spinner.
                pct = 0.0
            if (
                not force
                and now - self._last_emit < 0.25
                and abs(pct - self._last_pct) < 0.5
            ):
                return
            self._last_emit = now
            self._last_pct = pct
            desc = str(self.desc or "download").strip() or "download"
            if self.total and float(self.total) > 0:
                desc = f"{desc} ({self.n}/{self.total})"
            # Newline marker: reliable through redirected pipes on Windows.
            print(f"@@PROGRESS@@|{pct:.1f}|{desc}", flush=True)

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
    expected = civitai_expected_bytes(entry)
    local = _file_size(dest)
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
    print("  downloading VLM weights (large)…")
    VLM_DIR.mkdir(parents=True, exist_ok=True)
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
